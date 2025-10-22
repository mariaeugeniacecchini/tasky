# Tasky - Sistema de Gestión de Gastos Inteligente

Tasky es un bot de Telegram inteligente para la gestión automática de gastos y facturas, utilizando OCR con IA para procesar comprobantes y transferencias bancarias de forma automática.

## -+ Características Principales

- **Procesamiento Automático**: Extrae datos de facturas y transferencias bancarias usando OCR + IA
- **Categorización Inteligente**: Clasifica automáticamente gastos en categorías predefinidas
- **Transferencias Bancarias**: Procesamiento especializado para comprobantes de Santander y otros bancos
- **Reportes Visuales**: Genera gráficos de dona y barras para análisis de gastos
- **Comandos Flexibles**: Interface simple a través de Telegram

##  Arquitectura

### Tecnologías Utilizadas

- **Backend**:
  - Python 3.11+ (Bot de Telegram y servicio OCR)
  - Flask (API REST para procesamiento OCR)
  - PostgreSQL (Base de datos)
  - Docker & Docker Compose (Containerización)

- **IA y Procesamiento**:
  - OpenAI GPT-4o-mini (Análisis de documentos)
  - Tesseract OCR (Extracción de texto)
  - PyPDF2 (Procesamiento de PDFs)

- **Visualización**:
  - Matplotlib (Gráficos estadísticos)
  - Python Telegram Bot API



### Servicios Containerizados

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Telegram Bot  │    │   OCR Service   │    │   PostgreSQL    │
│    (Python)     │◄──►│    (Flask)      │    │   (Database)    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

##  Instalación y Configuración

### Prerequisitos

- Docker Desktop
- Docker Compose
- Cuenta de Telegram y bot token
- API Key de OpenAI

### Configuración de Secretos

1. **Crear los archivos de secretos**:
```bash
mkdir secrets
echo "tu_token_de_telegram" > secrets/telegram_token.txt
echo "tu_api_key_openai" > secrets/openai_api_key.txt
echo "password_base_datos" > secrets/db_pass.txt
```

2. **Configurar variables de entorno** (opcional):
```bash
# En el archivo .env (opcional)
TELEGRAM_TOKEN=tu_token_aqui
OPENAI_API_KEY=tu_api_key_aqui
```

### Iniciar el Sistema

```bash
# Clonar el repositorio
git clone <tu-repositorio>
cd tasky

# Iniciar todos los servicios
docker-compose up -d

# Verificar que todos los contenedores estén funcionando
docker-compose ps
```

### Verificar la Instalación

```bash
# Ver logs del bot
docker logs telegram_bot

# Ver logs del servicio OCR
docker logs ocr_ia
```

##  Manual de Uso

### Comandos Disponibles

#### `/resumen <mes>`
Genera un resumen mensual con gráfico de dona y detalles.

**Ejemplo**:
```
/resumen octubre
/resumen diciembre
```

**Resultado**:
- Gráfico de dona con distribución por categorías
- Lista detallada de gastos
- Total mensual

#### `/resumen_general`
Muestra un gráfico de barras con el historial completo de gastos por mes.

**Ejemplo**:
```
/resumen_general
```

**Resultado**:
- Gráfico de barras con gastos por mes/año
- Comparación histórica de gastos


### Procesamiento de Documentos

#### Facturas Regulares
Simplemente envía la imagen o PDF de la factura al bot. El sistema automáticamente:

1. Extrae: proveedor, fecha, monto total, items
2. Categoriza según el tipo de comercio
3. Almacena en la base de datos
4. Confirma el procesamiento

**Categorías Automáticas**:
- Supermercado
- Delivery (PedidosYa, Rappi)
- Petshop
- Farmacia
- Servicios
- Otros

#### Transferencias Bancarias
Para comprobantes de transferencias (especialmente Santander):

1. **Alquiler**: Transferencias a destinatarios configurados para alquileres
2. **Expensas**: Transferencias a administraciones de consorcios configuradas
3. **Otros**: Cualquier otra transferencia

**Procesamiento Automático**:
- Detecta el tipo de documento (factura vs transferencia)
- Extrae el destinatario real (no el banco)
- Corrige montos en formato argentino
- Categoriza según destinatario

## 🔧 Configuración Avanzada

### Modificar Categorías de Transferencia

Edita el archivo `telegram_bot/main.py` en la función `corregir_categoria_transferencia()`:

```python
def corregir_categoria_transferencia(proveedor: str, categoria_original: str) -> str:
    proveedor_lower = proveedor.lower().strip()
    
    # Configurar destinatarios para alquileres
    if "nombre_propietario" in proveedor_lower:
        return "Alquiler"
    
    # Configurar destinatarios para expensas
    if "administracion_edificio" in proveedor_lower:
        return "Expensas"
    # ...
```

### Agregar Nuevas Categorías

1. **Modificar el servicio OCR** (`ocr_ia/invoice_ai_service.py`):
```python
# En el prompt, agregar la nueva categoría
- Nueva_Categoria
```

2. **Actualizar la base de datos** si es necesario.

##  Troubleshooting

### Problemas Comunes

**Error: "No se encontró TELEGRAM_TOKEN"**
```bash
# Verificar que el archivo existe
cat secrets/telegram_token.txt

# Reiniciar el contenedor
docker-compose restart telegram_bot
```

**Error: "OCR no respondió correctamente"**
```bash
# Verificar logs del servicio OCR
docker logs ocr_ia

# Reiniciar el servicio
docker-compose restart ocr_ia
```

**Base de datos no conecta**
```bash
# Verificar el contenedor de PostgreSQL
docker logs db_facturas

# Reiniciar todos los servicios
docker-compose down && docker-compose up -d
```

### Ver Logs Detallados

```bash
# Logs en tiempo real
docker-compose logs -f

# Logs de un servicio específico
docker logs -f telegram_bot
docker logs -f ocr_ia
```

## 📊 Estructura del Proyecto

```
tasky/
├── telegram_bot/          # Bot de Telegram
│   ├── main.py           # Lógica principal del bot
│   ├── requirements.txt  # Dependencias Python
│   └── Dockerfile        # Imagen del bot
├── ocr_ia/               # Servicio de OCR con IA
│   ├── invoice_ai_service.py  # API de procesamiento
│   ├── requirements.txt  # Dependencias Python
│   └── Dockerfile        # Imagen del servicio OCR
├── database/             # Configuración de BD
│   └── init.sql         # Script de inicialización
├── secrets/             # Archivos de configuración
└── docker-compose.yml   # Orquestación de servicios
```

##  Contribución

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/nueva-funcionalidad`)
3. Commit tus cambios (`git commit -am 'Agrega nueva funcionalidad'`)
4. Push a la rama (`git push origin feature/nueva-funcionalidad`)
5. Crea un Pull Request

