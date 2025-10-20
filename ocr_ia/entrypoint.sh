#!/bin/bash
# Cargar secretos desde /run/secrets
[ -f /run/secrets/openai_api_key ] && export OPENAI_API_KEY=$(cat /run/secrets/openai_api_key)

# Mostrar confirmación
echo "✅ Secrets cargados correctamente."

# Ejecutar la aplicación
exec "$@"
