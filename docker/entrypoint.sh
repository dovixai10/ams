#!/bin/sh
set -eu

echo "Waiting for PostgreSQL at ${DB_HOST:-db}:${DB_PORT:-5432}..."
until python -c "
import os
import psycopg
psycopg.connect(
    host=os.environ.get('DB_HOST', 'db'),
    port=os.environ.get('DB_PORT', '5432'),
    dbname=os.environ.get('DB_NAME', 'ams'),
    user=os.environ.get('DB_USER', 'ams'),
    password=os.environ.get('DB_PASSWORD', ''),
).close()
"; do
    sleep 2
done

python manage.py migrate --run-syncdb --noinput
python manage.py collectstatic --noinput
python manage.py seed_pms_permissions || true

exec "$@"
