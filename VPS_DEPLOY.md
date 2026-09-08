# Deploy AMS on a VPS

## Prerequisites

- Ubuntu/Debian VPS with Docker and Docker Compose plugin installed
- Git access to `https://github.com/dovixai10/ams.git`
- PostgreSQL database reachable from the VPS (external host or local)
- Domain or public IP pointed at the VPS (optional but recommended)

## First-time setup on the VPS

```bash
sudo apt update && sudo apt install -y git docker.io docker-compose-plugin
sudo usermod -aG docker $USER
# log out and back in so docker group applies

sudo mkdir -p /opt/ams
sudo chown $USER:$USER /opt/ams
cd /opt/ams

git clone https://github.com/dovixai10/ams.git .
cp .env.production.example .env
nano .env   # set SECRET_KEY, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, DB_*

chmod +x scripts/deploy-vps.sh
./scripts/deploy-vps.sh
```

Open `http://YOUR_VPS_IP` (or your domain). Nginx serves static/media and proxies to Gunicorn.

## Updates (each release)

```bash
cd /opt/ams
./scripts/deploy-vps.sh
```

The script pulls `main`, rebuilds containers, runs migrations via the entrypoint, and seeds PMS permissions.

## Useful commands

```bash
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
docker compose -f docker-compose.prod.yml exec web python manage.py migrate --run-syncdb
```

## HTTPS (recommended)

Use Certbot on the host or add a Caddy/Traefik container in front of Nginx. At minimum, set `CSRF_TRUSTED_ORIGINS` to your `https://` URLs.

## Local full stack (with bundled Postgres)

For development only, use `docker compose up --build` and `.env.example` instead of `docker-compose.prod.yml`.
