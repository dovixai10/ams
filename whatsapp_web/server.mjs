// Local helper for the AMS Django app: keeps "linked phone" WhatsApp sessions
// (QR-scanned, like WhatsApp Web) alive and sends messages through them.
//
//   node server.mjs        (or: npm start)
//
// It listens on 127.0.0.1 only and every request must carry the shared token
// (env WHATSAPP_WEB_TOKEN, or data/token which is created on first start and
// read by Django too). Login credentials live in data/sessions/<id>/ - treat
// that folder like a password: anyone holding it can act as the linked phone.
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import pino from 'pino';
import makeWASocket, {
  Browsers, DisconnectReason, fetchLatestBaileysVersion, jidNormalizedUser, useMultiFileAuthState,
} from '@whiskeysockets/baileys';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = process.env.WA_SIDECAR_DATA || path.join(HERE, 'data');
const SESSIONS_DIR = path.join(DATA_DIR, 'sessions');
const HOST = '127.0.0.1';
const PORT = Number(process.env.WA_SIDECAR_PORT || 3100);
const GROUP_CACHE_MS = 5 * 60 * 1000;
const SEND_GAP_MS = [1500, 3500]; // random pause between two sends on one phone - looks human, avoids flood limits
const SEND_TIMEOUT_MS = 30000;

fs.mkdirSync(SESSIONS_DIR, { recursive: true });

function loadToken() {
  if (process.env.WHATSAPP_WEB_TOKEN) return process.env.WHATSAPP_WEB_TOKEN;
  const file = path.join(DATA_DIR, 'token');
  if (!fs.existsSync(file)) fs.writeFileSync(file, crypto.randomBytes(32).toString('hex'), { mode: 0o600 });
  return fs.readFileSync(file, 'utf8').trim();
}
const TOKEN = loadToken();

const log = pino({ level: process.env.WA_LOG_LEVEL || 'info' });
const baileysLog = pino({ level: 'silent' });

/** id -> { id, sock, status, qr, phone, name, retries, stopped, groups, groupsAt, queue, lastSendAt } */
const sessions = new Map();
let waVersion = null;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sessionDir = (id) => path.join(SESSIONS_DIR, String(id));
const isValidId = (id) => /^\d{1,9}$/.test(id);

class HttpError extends Error {
  constructor(status, message, extra = {}) { super(message); this.status = status; this.extra = extra; }
}

function publicState(s) {
  if (!s) return { status: 'not_started', qr: null, phone: '', name: '' };
  return { status: s.status, qr: s.status === 'qr' ? s.qr : null, phone: s.phone || '', name: s.name || '' };
}

async function openSocket(s) {
  const { state, saveCreds } = await useMultiFileAuthState(sessionDir(s.id));
  if (!waVersion) {
    try { waVersion = (await fetchLatestBaileysVersion()).version; } catch { /* fall back to the library's bundled version */ }
  }
  const sock = makeWASocket({
    ...(waVersion ? { version: waVersion } : {}),
    auth: state,
    logger: baileysLog,
    browser: Browsers.appropriate('AMS Reports'),
    markOnlineOnConnect: false,
    syncFullHistory: false,
    generateHighQualityLinkPreview: false,
  });
  s.sock = sock;
  s.status = 'connecting';

  sock.ev.on('creds.update', saveCreds);
  sock.ev.on('connection.update', (update) => {
    if (s.sock !== sock) return; // a newer socket replaced this one
    const { connection, lastDisconnect, qr } = update;

    if (qr) { s.qr = qr; s.status = 'qr'; }

    if (connection === 'open') {
      s.status = 'connected'; s.qr = null; s.retries = 0;
      s.phone = sock.user?.id ? jidNormalizedUser(sock.user.id).split('@')[0] : '';
      s.name = sock.user?.name || '';
      log.info({ id: s.id, phone: s.phone }, 'session connected');
    }

    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      s.qr = null;
      if (s.stopped) return;
      if (code === DisconnectReason.loggedOut) {
        log.warn({ id: s.id }, 'phone logged this device out - credentials removed');
        s.status = 'logged_out';
        fs.rmSync(sessionDir(s.id), { recursive: true, force: true });
        return;
      }
      const neverLinked = !state.creds.registered;
      if (neverLinked && code !== DisconnectReason.restartRequired) {
        // QR expired unscanned - don't hammer WhatsApp, wait for someone to ask again.
        s.status = 'closed';
        log.info({ id: s.id, code }, 'QR not scanned in time');
        return;
      }
      s.status = 'connecting';
      const delay = code === DisconnectReason.restartRequired ? 0 : Math.min(30000, 1000 * 2 ** s.retries++);
      log.info({ id: s.id, code, delay }, 'connection closed - reconnecting');
      setTimeout(() => { if (!s.stopped && s.sock === sock) openSocket(s).catch((e) => fail(s, e)); }, delay);
    }
  });
}

function fail(s, error) {
  log.error({ id: s.id, err: String(error) }, 'session error');
  s.status = 'closed';
}

async function startSession(id) {
  let s = sessions.get(id);
  if (s && !['closed', 'logged_out'].includes(s.status)) return s; // already starting / connected / showing QR
  if (!s) {
    s = { id, sock: null, status: 'connecting', qr: null, phone: '', name: '', retries: 0, stopped: false, groups: null, groupsAt: 0, queue: Promise.resolve(), lastSendAt: 0 };
    sessions.set(id, s);
  }
  s.stopped = false; s.retries = 0; s.status = 'connecting'; s.qr = null;
  const old = s.sock;
  s.sock = null; // so the old socket's close event is ignored, not treated as a drop
  try { old?.end(undefined); } catch { /* old socket already gone */ }
  await openSocket(s);
  return s;
}

async function logoutSession(id) {
  const s = sessions.get(id);
  if (s) {
    s.stopped = true;
    try { await s.sock?.logout(); } catch { /* not connected - nothing to log out of */ }
    try { s.sock?.end(undefined); } catch { /* ignore */ }
    sessions.delete(id);
  }
  fs.rmSync(sessionDir(id), { recursive: true, force: true });
}

function requireConnected(s) {
  if (!s) throw new HttpError(409, 'This phone is not linked yet. Open "Linked phones" and scan the QR code.', { state: 'not_started', transient: false });
  if (s.status === 'connected') return;
  if (s.status === 'connecting') throw new HttpError(409, 'The linked phone is still (re)connecting - will retry shortly.', { state: s.status, transient: true });
  throw new HttpError(409, 'The linked phone is disconnected. Open "Linked phones" and scan the QR code again.', { state: s.status, transient: false });
}

async function listGroups(s, refresh = false) {
  requireConnected(s);
  if (!refresh && s.groups && Date.now() - s.groupsAt < GROUP_CACHE_MS) return s.groups;
  const all = await s.sock.groupFetchAllParticipating();
  s.groups = Object.values(all).map((g) => ({ id: g.id, subject: g.subject || '', size: (g.participants || []).length }));
  s.groups.sort((a, b) => a.subject.localeCompare(b.subject));
  s.groupsAt = Date.now();
  return s.groups;
}

async function resolveTarget(s, kind, to) {
  const raw = String(to || '').trim();
  if (!raw) throw new HttpError(422, 'No recipient given.', { transient: false });

  if (kind === 'group') {
    if (raw.endsWith('@g.us')) return raw;
    const wanted = raw.toLowerCase();
    const find = (groups) => groups.filter((g) => g.subject.trim().toLowerCase() === wanted);
    let matches = find(await listGroups(s));
    if (!matches.length) matches = find(await listGroups(s, true)); // maybe a group added since the cache was filled
    if (matches.length > 1) throw new HttpError(422, `More than one group is named "${raw}" on this phone - rename one, or use the group ID.`, { transient: false });
    if (!matches.length) {
      const known = (s.groups || []).slice(0, 8).map((g) => g.subject).join(', ');
      throw new HttpError(422, `This phone isn't in a group named "${raw}".${known ? ` Groups it is in: ${known}${s.groups.length > 8 ? ', ...' : ''}.` : ''}`, { transient: false });
    }
    return matches[0].id;
  }

  const digits = raw.replace(/\D/g, '');
  if (digits.length < 8) throw new HttpError(422, `"${raw}" isn't a valid phone number.`, { transient: false });
  const [found] = (await s.sock.onWhatsApp(`${digits}@s.whatsapp.net`)) || [];
  if (!found?.exists) throw new HttpError(422, `${digits} isn't registered on WhatsApp.`, { transient: false });
  return found.jid || `${digits}@s.whatsapp.net`;
}

function sendText(s, kind, to, text) {
  // One send at a time per phone, spaced out a little.
  const job = s.queue.then(async () => {
    requireConnected(s);
    const jid = await resolveTarget(s, kind, to);
    const wait = s.lastSendAt + SEND_GAP_MS[0] + Math.random() * (SEND_GAP_MS[1] - SEND_GAP_MS[0]) - Date.now();
    if (wait > 0) await sleep(wait);
    const sent = await Promise.race([
      s.sock.sendMessage(jid, { text }),
      sleep(SEND_TIMEOUT_MS).then(() => { throw new HttpError(504, 'WhatsApp did not confirm the message in time.', { transient: true }); }),
    ]);
    s.lastSendAt = Date.now();
    return { id: sent?.key?.id || '', to: jid };
  });
  s.queue = job.catch(() => {}); // a failed send must not block the next one
  return job;
}

// ---------------------------------------------------------------- HTTP ----

function readJson(req) {
  return new Promise((resolve, reject) => {
    let size = 0; const chunks = [];
    req.on('data', (c) => { size += c.length; if (size > 200_000) { reject(new HttpError(413, 'Body too large')); req.destroy(); } else chunks.push(c); });
    req.on('end', () => {
      if (!chunks.length) return resolve({});
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); } catch { reject(new HttpError(400, 'Invalid JSON')); }
    });
    req.on('error', reject);
  });
}

function authorised(req) {
  const given = Buffer.from(String(req.headers['x-sidecar-token'] || ''));
  const want = Buffer.from(TOKEN);
  return given.length === want.length && crypto.timingSafeEqual(given, want);
}

async function route(req, res) {
  const url = new URL(req.url, `http://${HOST}`);
  const parts = url.pathname.split('/').filter(Boolean);

  if (req.method === 'GET' && url.pathname === '/health') return { ok: true, sessions: sessions.size };
  if (parts[0] !== 'sessions' || !parts[1]) throw new HttpError(404, 'Not found');
  const id = parts[1];
  if (!isValidId(id)) throw new HttpError(400, 'Bad session id');
  const action = parts[2] || '';
  const s = sessions.get(id);

  if (req.method === 'GET' && !action) return publicState(s);
  if (req.method === 'POST' && action === 'start') return publicState(await startSession(id));
  if (req.method === 'POST' && action === 'logout') { await logoutSession(id); return { status: 'logged_out' }; }
  if (req.method === 'GET' && action === 'groups') return { groups: await listGroups(s, url.searchParams.get('refresh') === '1') };
  if (req.method === 'POST' && action === 'send') {
    const body = await readJson(req);
    if (!body.text || typeof body.text !== 'string') throw new HttpError(400, 'text is required');
    if (!['person', 'group'].includes(body.kind)) throw new HttpError(400, 'kind must be person or group');
    return await sendText(requireSession(s), body.kind, body.to, body.text);
  }
  throw new HttpError(404, 'Not found');
}

function requireSession(s) { requireConnected(s); return s; }

const server = http.createServer(async (req, res) => {
  const reply = (status, body) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); };
  try {
    if (!authorised(req)) return reply(401, { error: 'Bad or missing token' });
    reply(200, await route(req, res));
  } catch (e) {
    if (e instanceof HttpError) return reply(e.status, { error: e.message, ...e.extra });
    log.error({ err: String(e) }, 'request failed');
    reply(500, { error: `WhatsApp helper error: ${e.message || e}`, transient: true });
  }
});

server.listen(PORT, HOST, () => {
  log.info(`AMS WhatsApp helper listening on http://${HOST}:${PORT}`);
  // Bring back every phone that was linked before the restart (no new QR needed).
  const saved = fs.readdirSync(SESSIONS_DIR).filter((id) => isValidId(id) && fs.existsSync(path.join(sessionDir(id), 'creds.json')));
  saved.forEach((id, i) => setTimeout(() => startSession(id).catch((e) => log.error({ id, err: String(e) }, 'restore failed')), i * 2000));
  if (saved.length) log.info({ sessions: saved }, 'restoring linked phones');
});

process.on('uncaughtException', (e) => log.error({ err: String(e) }, 'uncaught exception'));
process.on('unhandledRejection', (e) => log.error({ err: String(e) }, 'unhandled rejection'));
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    sessions.forEach((s) => { s.stopped = true; try { s.sock?.end(undefined); } catch { /* ignore */ } });
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 1500);
  });
}
