#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/django_hw}"
PA_USERNAME="${PA_USERNAME:-olomar}"
PA_DOMAIN="${PA_DOMAIN:-olomar.pythonanywhere.com}"
PA_TOKEN_FILE="${PA_TOKEN_FILE:-$HOME/.pa_api_token}"

if [[ -z "${PA_API_TOKEN:-}" && -f "$PA_TOKEN_FILE" ]]; then
    PA_API_TOKEN="$(tr -d '[:space:]' < "$PA_TOKEN_FILE")"
fi
if [[ -z "${PA_API_TOKEN:-}" ]]; then
    echo "Не задан PA_API_TOKEN (переменная окружения или $PA_TOKEN_FILE)." >&2
    exit 1
fi

cd "$APP_DIR"

echo "==> git pull"
git pull --ff-only

if [[ -d venv ]]; then
    . venv/bin/activate
elif [[ -d .venv ]]; then
    . .venv/bin/activate
fi

echo "==> django check"
python manage.py check

echo "==> migrate"
python manage.py migrate --noinput

if [[ "${SKIP_COLLECTSTATIC:-0}" != "1" ]]; then
    echo "==> collectstatic"
    python manage.py collectstatic --noinput > /dev/null
fi

echo "==> reload web app"
curl -fsS -X POST \
    -H "Authorization: Token $PA_API_TOKEN" \
    "https://www.pythonanywhere.com/api/v0/user/$PA_USERNAME/webapps/$PA_DOMAIN/reload/" > /dev/null

echo "Готово: https://$PA_DOMAIN"
