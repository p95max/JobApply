#!/usr/bin/env sh
set -eu

echo "[entrypoint] Installing deps (dev-friendly)..."
poetry install --no-interaction --no-ansi

echo "[entrypoint] Waiting DB..."
i=0
until poetry run python -c "import os; import psycopg; psycopg.connect(host=os.getenv('POSTGRES_HOST','db'), port=os.getenv('POSTGRES_PORT','5432'), dbname=os.getenv('POSTGRES_DB','jobapply'), user=os.getenv('POSTGRES_USER','jobapply'), password=os.getenv('POSTGRES_PASSWORD','jobapply')).close(); print('db ok')" >/dev/null 2>&1
do
  i=$((i+1))
  if [ "$i" -gt 60 ]; then
    echo "ERROR: DB is not ready"
    exit 1
  fi
  sleep 1
done

echo "[entrypoint] Makemigrations..."
poetry run python manage.py makemigrations --noinput

echo "[entrypoint] Migrate..."
poetry run python manage.py migrate --noinput

echo "[entrypoint] Create social account(env, idempotent)..."
poetry run python manage.py create_google_socialapp_if_not_exists

echo "[entrypoint] Create superuser (env, idempotent)..."
poetry run python manage.py create_superuser_if_not_exists

echo "[entrypoint] Start server..."
exec poetry run python manage.py runserver 0.0.0.0:8000
