# Run AMS with Docker Compose

## Prerequisites

- Docker Desktop with Docker Compose enabled

## Start locally

1. Copy `.env.example` to `.env`.
2. Replace `SECRET_KEY` and `POSTGRES_PASSWORD` with local values.
3. Start the application:

   ```sh
   docker compose up --build
   ```

4. Open http://localhost:8000.

The `web` service waits for PostgreSQL, runs Django migrations (including
unmigrated app tables via `--run-syncdb`), collects static assets, then starts
Gunicorn.

## Common commands

```sh
# Start in the background
docker compose up --build -d

# Follow application logs
docker compose logs -f web

# Run a Django command
docker compose exec web python manage.py createsuperuser

# Stop containers while preserving database and uploaded media
docker compose down

# Remove all local Docker data and start fresh
docker compose down -v
```

PostgreSQL data, uploaded media, and collected static assets are stored in
named Docker volumes. Do not use `docker compose down -v` unless the local data
can be discarded.
