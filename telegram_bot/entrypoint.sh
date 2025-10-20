#!/bin/bash
# Cargar secretos desde /run/secrets
[ -f /run/secrets/db_pass ] && export DB_PASS=$(cat /run/secrets/db_pass)
[ -f /run/secrets/telegram_token ] && export TELEGRAM_TOKEN=$(cat /run/secrets/telegram_token)
[ -f /run/secrets/openai_api_key ] && export OPENAI_API_KEY=$(cat /run/secrets/openai_api_key)

# Mostrar confirmación
echo "✅ Secrets cargados correctamente."

# Ejecutar la aplicación
exec "$@"
