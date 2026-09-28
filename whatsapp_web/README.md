# WhatsApp linked-phone helper

Keeps QR-linked WhatsApp sessions alive and sends messages for the AMS Django app
(Integrations - WhatsApp - Linked Phones). Uses the unofficial
[Baileys](https://github.com/WhiskeySockets/Baileys) library, so WhatsApp may restrict a number
that sends automated messages - keep it to a few internal recipients.

## Run

```
cd whatsapp_web
npm install          # first time only
node server.mjs      # keep this running (needed for scheduled sends over QR)
```

It listens on `127.0.0.1:3100` only. Django finds it via `WHATSAPP_WEB_URL` (default `http://127.0.0.1:3100`).

## Security

- `data/token` is a shared secret created on first start; Django reads the same file
  (or set `WHATSAPP_WEB_TOKEN` in both places).
- `data/sessions/<id>/` holds the linked phones' login. Anyone with that folder can act as the phone -
  back it up like a password and never commit it (already in `.gitignore`).
- Linked phones reconnect by themselves after a restart; no new QR is needed unless the phone
  removes the device under *Linked devices*.

## Env

| Variable | Default | Meaning |
|---|---|---|
| `WA_SIDECAR_PORT` | `3100` | Port to listen on |
| `WA_SIDECAR_DATA` | `./data` | Where tokens and logins are kept |
| `WHATSAPP_WEB_TOKEN` | contents of `data/token` | Shared secret |
| `WA_LOG_LEVEL` | `info` | pino log level |
