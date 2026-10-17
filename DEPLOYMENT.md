# Server Deployment Guide

How to set up and run this app (Django + Celery + the WhatsApp linked-phone
helper) on a real server, end to end. Written for a fresh Linux server
(Ubuntu/Debian commands shown); adjust package-manager commands if you're on
something else.

## What actually has to run together

| Process | What it does | How it's started |
|---|---|---|
| Django (via Gunicorn) | The web app itself | `gunicorn` behind Nginx |
| PostgreSQL | The database | already hosted on Supabase per `.env` - see note below |
| Redis | Celery's broker (queues "ams", on db index 5) | system service |
| Celery worker | Sends scheduled WhatsApp reports, polls CRM WhatsApp leads | systemd service |
| Celery beat | Triggers the worker's scheduled jobs (every 30-60s) | systemd service |
| WhatsApp linked-phone helper (Node) | Keeps QR-linked WhatsApp sessions alive, sends messages | systemd service (`whatsapp_web/server.mjs`) |
| Nginx | Reverse proxy + serves `/static/` and `/media/` directly | system service |

If any one of Celery worker/beat or the Node helper isn't running, the app's
web pages still work fine - only the features that depend on them silently
stop doing their job (scheduled reports don't send, the Linked Phones screen
shows "helper service isn't running").

**Database note:** this project currently points at a remote Supabase
Postgres instance (see `DB_HOST` in `.env`), not a local Postgres install. If
that's intentional, skip the "Install PostgreSQL" step below entirely. If you
want a self-hosted DB on the server instead, install Postgres and update
`DB_*` in `.env` to point at it.

---

## 1. System packages

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip \
  build-essential cmake git \
  libpq-dev \
  redis-server \
  nginx \
  curl
```

- `cmake` + `build-essential` are required to compile `dlib` (face
  recognition) from source - this is the slowest part of setup, can take
  10-20+ minutes on a small server. If it fails on a low-RAM VPS, add a swap
  file first (dlib's compile step is memory-hungry).
- `libpq-dev` is needed for `psycopg` (Postgres driver) to build.
- Only install local Postgres if you're not using the remote Supabase DB
  (see note above).

**Node.js** (for the WhatsApp helper - needs >= 20):
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version   # confirm >= 20
```

---

## 2. Get the code

```bash
git clone <your-repo-url> /opt/ams
cd /opt/ams
git checkout dev   # or whichever branch you're deploying
```

---

## 3. Python environment

```bash
cd /opt/ams
python3.12 -m venv prakharenv
source prakharenv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn   # not currently in requirements.txt - add it
```

This installs Django, Celery, DRF, face-recognition/dlib, cryptography,
qrcode, etc. - everything in `requirements.txt`.

---

## 4. Environment variables

```bash
cp .env.example .env
nano .env   # fill in real values
```

Fill in at minimum, for a real production deployment:

- `SECRET_KEY` - generate one (`python -c "import secrets; print(secrets.token_urlsafe(50))"`) and set it explicitly. If left blank, the app auto-generates one into `secret_key.txt` on first run and reuses it after - fine for a single server, but set it explicitly if you ever run multiple app instances (they'd otherwise each generate their own, breaking session/JWT compatibility between them).
- `DEBUG=False` - **must** be False in production (shows full tracebacks to visitors otherwise).
- `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` - your production database.
- `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` - a Gmail address + App Password (not your real Gmail password) for outgoing mail.
- `CELERY_BROKER_URL` - defaults to `redis://localhost:6379/5`, fine if Redis is on the same server.
- `INTEGRATION_ENCRYPTION_KEY` - **set this explicitly in production** (a Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`). If left unset it derives from `SECRET_KEY`, which means rotating `SECRET_KEY` later would make every already-saved WhatsApp integration token unreadable.
- `WHATSAPP_WEB_TOKEN` - leave blank the first time; the Node helper (step 8) generates one into `whatsapp_web/data/token` on first start, and you can copy that value back into `.env` afterward if you want Django to pin it explicitly rather than reading the file.

**Also check `config/settings.py` directly** - `ALLOWED_HOSTS` and
`CSRF_TRUSTED_ORIGINS` are hardcoded lists in that file (not read from
`.env`), currently containing dev/ngrok URLs and a `"*"` wildcard. Before
going live on your real domain, add that domain to both lists (and consider
removing the `"*"` wildcard from `ALLOWED_HOSTS` once you've confirmed the
real domain works, since `"*"` accepts any Host header).

---

## 5. Database

```bash
source prakharenv/bin/activate
python manage.py migrate
```

**This step is the single most common cause of live-site 500 errors in this
project** - if it's skipped (or run partially and fails partway through),
pages that touch newer parts of the schema (creating/editing/deleting
employees, invoices, CRM leads, etc.) will 500 with "relation ... does not
exist" even though the confirmation/listing pages looked fine. Always run
`migrate` after every deploy that includes new code, not just the first
time. `python manage.py showmigrations employees | grep '\[ \]'` shows any
unapplied ones.

Create your platform admin account:
```bash
python manage.py createsuperuser
```

---

## 6. Static & media files

Since `WhiteNoiseMiddleware` is commented out in `settings.py` and the app
only self-serves `/static/`+`/media/` when `DEBUG=True`, **Nginx must serve
these directly** once `DEBUG=False`. Collect static files first:

```bash
python manage.py collectstatic --noinput
```

This populates `staticfiles/` (per `STATIC_ROOT`). `media/` already exists
and holds uploaded files (logos, documents, invoices, attendance photos) -
back this up along with the database, it's real user data.

---

## 7. Firebase (push notifications) - optional

If you want mobile push notifications working: download the service-account
JSON from Firebase Console → Project Settings → Service Accounts → Generate
new private key, and place it at the path `FIREBASE_CREDENTIALS_PATH` points
to in `.env` (default: `firebase-service-account.json` at the project root).
If you skip this, push sending just no-ops quietly - not an error.

---

## 8. WhatsApp linked-phone helper (Node)

```bash
cd /opt/ams/whatsapp_web
npm install
node server.mjs   # test it starts; Ctrl+C once you see "listening on 127.0.0.1:3100"
```

It listens on `127.0.0.1` only (not reachable from outside the server) and
authenticates Django's requests via a shared token in `data/token`
(auto-created on first run). It needs to be a long-running, auto-restarting
process - see the systemd unit in step 10. `whatsapp_web/data/sessions/`
holds the actual linked-phone login credentials once an admin scans the QR
code from the app's Integrations screen - **back this up and never delete
it**, or every linked phone has to be re-scanned.

---

## 9. Gunicorn

A starter config already exists at `gunicorn-cfg.py`, but it's template
boilerplate (binds `0.0.0.0:5005`, 1 worker) - adjust for your server:

```python
# gunicorn-cfg.py
bind = '127.0.0.1:5005'       # behind Nginx, not exposed directly
workers = 3                    # roughly (2 x CPU cores) + 1
accesslog = '-'
errorlog = '-'
loglevel = 'info'
timeout = 60                   # face-recognition requests can take a few seconds
```

Test it manually first:
```bash
source prakharenv/bin/activate
gunicorn config.wsgi:application -c gunicorn-cfg.py
```

---

## 10. Run everything as systemd services

Create these under `/etc/systemd/system/`, then `sudo systemctl daemon-reload`
and `sudo systemctl enable --now <name>` each one.

**`ams-gunicorn.service`**
```ini
[Unit]
Description=AMS Django app (Gunicorn)
After=network.target

[Service]
WorkingDirectory=/opt/ams
ExecStart=/opt/ams/prakharenv/bin/gunicorn config.wsgi:application -c gunicorn-cfg.py
Restart=always
User=www-data
EnvironmentFile=/opt/ams/.env

[Install]
WantedBy=multi-user.target
```

**`ams-celery-worker.service`**
```ini
[Unit]
Description=AMS Celery worker
After=network.target redis-server.service

[Service]
WorkingDirectory=/opt/ams
# --pool=solo in the project's own dev notes is a Windows-only workaround -
# on Linux use the real default (prefork) with a concurrency you're
# comfortable with, or omit --concurrency to let Celery pick automatically.
ExecStart=/opt/ams/prakharenv/bin/celery -A config worker -l info -Q ams --concurrency=2
Restart=always
User=www-data
EnvironmentFile=/opt/ams/.env

[Install]
WantedBy=multi-user.target
```

**`ams-celery-beat.service`**
```ini
[Unit]
Description=AMS Celery beat (scheduler)
After=network.target redis-server.service

[Service]
WorkingDirectory=/opt/ams
ExecStart=/opt/ams/prakharenv/bin/celery -A config beat -l info
Restart=always
User=www-data
EnvironmentFile=/opt/ams/.env

[Install]
WantedBy=multi-user.target
```

**`ams-whatsapp-web.service`**
```ini
[Unit]
Description=AMS WhatsApp linked-phone helper (Baileys)
After=network.target

[Service]
WorkingDirectory=/opt/ams/whatsapp_web
ExecStart=/usr/bin/node server.mjs
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

Check status / logs for any of them:
```bash
sudo systemctl status ams-gunicorn
sudo journalctl -u ams-celery-worker -f
```

---

## 11. Nginx

Adapt `nginx/web-project-django.conf` (currently generic template
boilerplate on port 5050) into something like:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 20M;   # attendance photos, documents, invoice PDFs

    location /static/ {
        alias /opt/ams/staticfiles/;
    }
    location /media/ {
        alias /opt/ams/media/;
    }

    location / {
        proxy_pass http://127.0.0.1:5005;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Symlink it into `/etc/nginx/sites-enabled/`, then:
```bash
sudo nginx -t && sudo systemctl reload nginx
```

Then add HTTPS with Certbot (Let's Encrypt):
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## Redeploy checklist (every time you push new code to live)

This is the sequence that's been the root cause of most of this project's
live-only 500 errors when skipped:

```bash
cd /opt/ams
git pull
source prakharenv/bin/activate
pip install -r requirements.txt     # in case dependencies changed
python manage.py migrate            # <-- the step most often forgotten
python manage.py collectstatic --noinput
sudo systemctl restart ams-gunicorn ams-celery-worker ams-celery-beat
```

(The WhatsApp helper only needs restarting if `whatsapp_web/server.mjs`
itself changed - restarting it unnecessarily briefly drops the live
connection, which auto-reconnects, so it's harmless but needless.)

---

## Troubleshooting quick reference

- **500 on create/edit/delete for Employees, Invoices, CRM Leads, etc.** → almost always unapplied migrations. Run `python manage.py showmigrations employees` and look for `[ ]` lines, then `migrate`.
- **"The WhatsApp helper service isn't running"** → `ams-whatsapp-web` service isn't up; check `sudo systemctl status ams-whatsapp-web`.
- **Scheduled WhatsApp reports / CRM lead polling not happening** → `ams-celery-worker` and/or `ams-celery-beat` aren't running, or Redis isn't reachable.
- **Attendance check-in says you're far away when you're not** → the employee's *Branch* location (not just the Office's) may have stale coordinates copied at the time the branch was created - check the Branch's own lat/long, not just the Office profile page.
- **CSS/JS changes not showing up live** → you forgot `collectstatic` after the deploy, or the browser/CDN cached the old file (several static files in this project use a manually-bumped `?v=N` query string specifically to force a refresh - bump it if you change one of those files).
