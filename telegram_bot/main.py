import os
import json
import psycopg2
import requests
from datetime import datetime
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from decimal import Decimal

# Forzar backend sin GUI (para matplotlib dentro de Docker)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np
from io import BytesIO



#config

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
OCR_URL = os.getenv("OCR_URL", "http://ocr_ia:5000/process")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASS", "admin123")
DB_NAME = os.getenv("DB_NAME", "facturas_db")
DB_HOST = os.getenv("DB_HOST", "db_facturas")



if not BOT_TOKEN:
    raise SystemExit("ERROR: No se encontró TELEGRAM_TOKEN en las variables de entorno (.env).")



# db
conn = psycopg2.connect(
    host=DB_HOST,
    database=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD
)
conn.autocommit = True





async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 ¡Hola! Envíame una foto de una factura para procesarla.")


def parse_fecha_o_none(fecha_str: str):
    """Convierte texto de fecha a datetime.date o devuelve None si no es válida."""
    if not fecha_str:
        return None
    formatos = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"]
    for fmt in formatos:
        try:
            f = datetime.strptime(fecha_str.strip(), fmt).date()
            hoy = datetime.today().date()
            
            if f >= hoy or f.year < 2000:
                return None
            return f
        except Exception:
            continue
    return None


def corregir_categoria_transferencia(proveedor: str, categoria_original: str) -> str:
    """Corrige la categorización basada en el proveedor para transferencias bancarias."""
    proveedor_lower = proveedor.lower().strip()
    
    # Categorías específicas por destinatario
    if "menno gabriela" in proveedor_lower:
        return "Alquiler"
    if "grupo zafche" in proveedor_lower:
        return "Alquiler"
    if "cons ed mistica" in proveedor_lower:
        return "Expensas"
    if "mistica" in proveedor_lower:
        return "Expensas"
    if "calle 7" in proveedor_lower:
        return "Expensas"
    if "num 39" in proveedor_lower:
        return "Expensas"
    if "ed mistica" in proveedor_lower:
        return "Expensas"
    
    
    if categoria_original == "Servicios" and any(palabra in proveedor_lower for palabra in ["transferencia", "santander", "galicia"]):
        return "Otros"
    
    
    if any(word in proveedor_lower for word in ["cons", "consorcio", "edificio", "expensas"]):
        return "Expensas"
    
    return categoria_original


def corregir_monto_transferencia(total_original: float) -> float:
    """Corrige montos mal interpretados por el OCR."""
    
    # Si es un monto que parece estar dividido por 10
    if 10000 <= total_original <= 99999: 
        return total_original * 10
    
    # Si es muy pequeño para una transferencia real
    elif 1000 <= total_original <= 9999:  # Entre 1k y 9k
        return total_original * 10
    
    # Si es demasiado grande, dividir
    elif total_original > 1000000:
        return total_original / 10
    
    return total_original


async def process_invoice_file(update: Update, file_path: str, file_name: str, mime_type: str):
    try:
        
        response = requests.post(OCR_URL, files={"file": (file_name, open(file_path, "rb"), mime_type)})

        if response.status_code != 200:
            await update.message.reply_text("Error al procesar la factura (OCR no respondió correctamente).")
            return

        data = response.json()

        
        if not all(k in data for k in ("proveedor", "fecha", "total", "categoria")):
            await update.message.reply_text("La respuesta del OCR está incompleta.")
            return

        proveedor = data["proveedor"].strip()
        categoria = data.get("categoria", "Otros")

       
        
        if proveedor.lower() in ["santander", "galicia", "bbva", "hsbc", "macro", "nación", "provincia"]:

            await update.message.reply_text(f"Error: Detecté '{proveedor}' como proveedor. Debería ser el destinatario de la transferencia. Reenvía la imagen.")
            return

        categoria = corregir_categoria_transferencia(proveedor, categoria)

        # Parsear fecha y total
        fecha = parse_fecha_o_none(data.get("fecha"))

       
        raw_total = str(data.get("total", "")).strip()

        if raw_total:
            limpio = raw_total.replace(".", "").replace(",", ".")
            try:
                total = float(limpio)
            except Exception:
                total = 0.0
        else:
            total = 0.0

        
        total = corregir_monto_transferencia(total)


        cursor = conn.cursor()

        # Insertar o reutilizar proveedor
        cursor.execute("""
            INSERT INTO proveedores (nombre)
            VALUES (%s)
            ON CONFLICT (nombre) DO UPDATE SET nombre = EXCLUDED.nombre
            RETURNING id;
        """, (proveedor,))
        proveedor_id = cursor.fetchone()[0]

        # Evitar duplicados 
        if fecha is not None:
            cursor.execute("""
                SELECT id FROM facturas
                WHERE proveedor_id = %s AND fecha = %s AND total = %s;
            """, (proveedor_id, fecha, total))
        else:
            cursor.execute("""
                SELECT id FROM facturas
                WHERE proveedor_id = %s AND fecha IS NULL AND total = %s;
            """, (proveedor_id, total))

        if cursor.fetchone():
            fecha_texto = f"del {fecha.strftime('%d/%m/%Y')}" if fecha else "(sin fecha)"
            await update.message.reply_text(
                f" La factura de {proveedor} {fecha_texto} ya está registrada."
            )
            cursor.close()
            return

        # Insertar factura
        cursor.execute("""
            INSERT INTO facturas (proveedor_id, fecha, total, categoria, raw_json)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
        """, (proveedor_id, fecha, total, categoria, json.dumps(data)))
        factura_id = cursor.fetchone()[0]

        # Insertar ítems
        if "items" in data and isinstance(data["items"], list):
            for item in data["items"]:
                descripcion = item.get("nombre", "Sin descripción")
                precio = item.get("precio", 0)
                try:
                    precio = float(str(precio).replace(",", "."))
                except:
                    precio = 0.0

                cursor.execute("""
                    INSERT INTO items (factura_id, descripcion, precio_total)
                    VALUES (%s, %s, %s);
                """, (factura_id, descripcion, precio))

        cursor.close()

        # Resumen para el usuario
        resumen = (
            f"🧾 *Factura registrada:*\n"
            f"🏢 *Proveedor:* {proveedor}\n"
            f"📅 *Fecha:* {fecha.strftime('%d/%m/%Y') if fecha else '—'}\n"
            f"💰 *Total:* ${total:,.2f}\n"
            f"📂 *Categoría:* {categoria}"
        )
        await update.message.reply_text(resumen, parse_mode="Markdown")

    except Exception as e:
        import traceback

        await update.message.reply_text(f"Error al procesar la factura.\nDetalles: {e}")


#handlers
async def handle_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        file_path = "/tmp/factura.jpg"
        await file.download_to_drive(file_path)
        await process_invoice_file(update, file_path, "factura.jpg", "image/jpeg")
    except Exception as e:
        import traceback

        await update.message.reply_text(f"Error al procesar la imagen.\nDetalles: {e}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        document = update.message.document
        if not document.mime_type.startswith("application/pdf"):
            await update.message.reply_text("Solo se admiten archivos PDF.")
            return

        file = await document.get_file()
        file_path = f"/tmp/{document.file_name}"
        await file.download_to_drive(file_path)
        await process_invoice_file(update, file_path, document.file_name, "application/pdf")
    except Exception as e:
        import traceback

        await update.message.reply_text(f" Error al procesar el PDF.\nDetalles: {e}")




#conmandos

async def gastos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.nombre, SUM(f.total)
        FROM facturas f
        JOIN proveedores p ON p.id = f.proveedor_id
        GROUP BY p.nombre
        ORDER BY SUM(f.total) DESC;
    """)
    rows = cursor.fetchall()
    cursor.close()

    if rows:
        text = " *Gasto por proveedor:*\n"
        for prov, suma in rows:
            text += f"• {prov}: ${suma:,.2f}\n"
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(" No hay datos registrados aún.")


async def resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cursor = conn.cursor()

        
        meses = {
            "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
            "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10,
            "Noviembre": 11, "Diciembre": 12
        }

        args = context.args
        if args:
            mes_nombre = args[0].capitalize()
            mes_num = meses.get(mes_nombre)
            if not mes_num:
                await update.message.reply_text("Mes no válido. Ejemplo: /resumen Octubre")
                cursor.close()
                return
        else:
            # si no se especifica mes, usar el mes actual
            mes_actual = datetime.now().month
            mes_num = mes_actual
            mes_nombre = [k for k, v in meses.items() if v == mes_num][0]

        # totales por categoría
        cursor.execute("""
            SELECT categoria, SUM(total)
            FROM facturas
            WHERE EXTRACT(MONTH FROM fecha) = %s
            GROUP BY categoria
            ORDER BY SUM(total) DESC;
        """, (mes_num,))
        rows = cursor.fetchall()
        cursor.close()

        if not rows:
            await update.message.reply_text(f"No hay facturas registradas para {mes_nombre}.")
            return

        
        categoria_aliases = {
            "comida/supermercado": "Supermercado",
            "supermercado": "Supermercado",
            "facturas/servicios": "Facturas/Servicios",
            "servicios": "Facturas/Servicios",
            "delivery": "Delivery",
            "farmacia": "Farmacia",
            "alquiler": "Alquiler",
            "expensas": "Expensas",
            "otros": "Otros",
            "petshop": "Petshop"
        }

        normalizados = {}
        for cat, val in rows:
            clave = cat.strip().lower()
            nombre_final = categoria_aliases.get(clave, cat.strip().title())
            normalizados[nombre_final] = normalizados.get(nombre_final, 0) + float(val)

        categorias = list(normalizados.keys())
        valores = list(normalizados.values())

        total = float(sum(valores))

        
        colores = ["#FF6B6B", "#FFD93D", "#6BCB77", "#4D96FF", "#C77DFF", "#FF9CEE"][:len(valores)]

        #grafico
        fig, ax = plt.subplots(figsize=(6.5, 6.5), dpi=200)

        wedges, _ = ax.pie(
            valores,
            startangle=90,
            colors=colores,
            wedgeprops=dict(width=0.4, edgecolor="white")
        )

        
        ax.text(
            0, 0, f"${total:,.0f}",
            ha="center", va="center",
            fontsize=22, fontweight="bold", color="#222"
        )

        
        for i, (wedge, valor) in enumerate(zip(wedges, valores)):
            ang = (wedge.theta2 + wedge.theta1) / 2
            ang_rad = np.deg2rad(ang)
            
            
            radio = 0.8  
            x = radio * np.cos(ang_rad)
            y = radio * np.sin(ang_rad)
            
            porcentaje = (valor / total) * 100 if total > 0 else 0
            
            
            if porcentaje >= 5:
                ax.text(
                    x, y,
                    f"{porcentaje:.1f}%",
                    ha="center", va="center",
                    fontsize=10,
                    color="white",
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="black", alpha=0.7, edgecolor="none")
                )

        
        ax.set_title(
            f"Gastos por categoría — {mes_nombre}",
            fontsize=15,
            fontweight="bold",
            pad=20
        )

        
        etiquetas_leyenda = []
        for categoria, valor in zip(categorias, valores):
            porcentaje = (valor / total) * 100 if total > 0 else 0
            etiquetas_leyenda.append(f"{categoria} ({porcentaje:.1f}%)")
            
        ax.legend(
            wedges,
            etiquetas_leyenda,
            title="Categorías",
            loc="lower center",
            bbox_to_anchor=(0.5, -0.25),
            fontsize=9.5,
            title_fontsize=11,
            ncol=2,
            frameon=False
        )

        fig.patch.set_facecolor("white")
        plt.tight_layout()

        # guardar imagen
        buffer = BytesIO()
        plt.savefig(buffer, format="png", bbox_inches="tight", dpi=200)
        buffer.seek(0)
        plt.close(fig)

        # enviar gráfico
        await update.message.reply_photo(photo=InputFile(buffer, filename=f"resumen_{mes_nombre}.png"))

        
        emoji_map = {
            "Farmacia": "💊",
            "Delivery": "🍔",
            "Supermercado": "🛒",
            "Facturas/Servicios": "📄",
            "Alquiler": "🏠",
            "Expensas": "🏢",
            "Otros": "📦",
            "Petshop": "🐈"
        }

        detalle = f"📋 *Detalle de gastos — {mes_nombre}:*\n"
        for categoria, valor in zip(categorias, valores):
            emoji = emoji_map.get(categoria, "📦")
            detalle += f"{emoji} {categoria}: ${valor:,.0f}\n"

        await update.message.reply_text(detalle, parse_mode="Markdown")

    except Exception as e:
        import traceback

        await update.message.reply_text("Error al generar el resumen mensual.")



async def resumen_general(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cursor = conn.cursor()

        
        meses_nombres = {
            1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
            7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
        }

        # determinar el año a mostrar
        args = context.args
        if args:
            try:
                año_objetivo = int(args[0])
            except ValueError:
                await update.message.reply_text("Año no válido. Ejemplo: /resumen_general 2025")
                cursor.close()
                return
        else:
            # si no se especifica año, usar el año actual
            año_objetivo = datetime.now().year

        # gastos totales por mes del año especificado
        cursor.execute("""
            SELECT EXTRACT(MONTH FROM fecha) as mes, SUM(total)
            FROM facturas
            WHERE fecha IS NOT NULL AND EXTRACT(YEAR FROM fecha) = %s
            GROUP BY EXTRACT(MONTH FROM fecha)
            ORDER BY mes;
        """, (año_objetivo,))
        rows = cursor.fetchall()
        cursor.close()

        if not rows:
            await update.message.reply_text(f"No hay facturas registradas para el año {año_objetivo}.")
            return

       
        meses_labels = []
        gastos_totales = []
        
        for mes_num, total in rows:
            mes_nombre = meses_nombres.get(int(mes_num), f"Mes {int(mes_num)}")
            meses_labels.append(mes_nombre)
            gastos_totales.append(float(total))

        #  gráfico de barras
        fig, ax = plt.subplots(figsize=(12, 7), dpi=200)
        
        
        colores = plt.cm.viridis(np.linspace(0, 1, len(gastos_totales)))
        
        bars = ax.bar(meses_labels, gastos_totales, color=colores, edgecolor='white', linewidth=0.7)
        
        
        for bar, valor in zip(bars, gastos_totales):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + max(gastos_totales)*0.01,
                   f'${valor:,.0f}', ha='center', va='bottom', fontsize=9, fontweight='bold')

        # personalización del gráfico 
        ax.set_title(f"Gastos Mensuales - {año_objetivo}", fontsize=16, fontweight="bold", pad=20)
        ax.set_ylabel("Gastos ($)", fontsize=12, fontweight="bold")
        ax.set_xlabel("Mes", fontsize=12, fontweight="bold")
        
        # rotar etiquetas del eje X si hay muchos meses
        if len(meses_labels) > 6:
            plt.xticks(rotation=45, ha='right')
        
       
        ax.grid(axis='y', alpha=0.3, linestyle='--')
        ax.set_axisbelow(True)
        
        
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
        
        fig.patch.set_facecolor("white")
        plt.tight_layout()

        
        buffer = BytesIO()
        plt.savefig(buffer, format="png", bbox_inches="tight", dpi=200)
        buffer.seek(0)
        plt.close(fig)

        
        await update.message.reply_photo(photo=InputFile(buffer, filename=f"gastos_mensuales_{año_objetivo}.png"))

        # resumen estadístico del historial
        total_general = sum(gastos_totales)
        promedio_mensual = total_general / len(gastos_totales) if gastos_totales else 0
        maximo_mes = max(gastos_totales) if gastos_totales else 0
        minimo_mes = min(gastos_totales) if gastos_totales else 0
        
        # encontrar el mes con mayor y menor gasto
        max_index = gastos_totales.index(maximo_mes) if gastos_totales else 0
        min_index = gastos_totales.index(minimo_mes) if gastos_totales else 0
        mes_mayor_gasto = meses_labels[max_index] if meses_labels else "N/A"
        mes_menor_gasto = meses_labels[min_index] if meses_labels else "N/A"

        detalle = (
            f"📊 *Resumen del año {año_objetivo}:*\n"
            f"💰 Total del año: ${total_general:,.0f}\n"
            f"📅 Meses con gastos: {len(gastos_totales)}\n"
            f"📈 Promedio mensual: ${promedio_mensual:,.0f}\n"
            f"🔥 Mayor gasto: ${maximo_mes:,.0f} ({mes_mayor_gasto})\n"
            f"💚 Menor gasto: ${minimo_mes:,.0f} ({mes_menor_gasto})"
        )

        await update.message.reply_text(detalle, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"Error al generar el resumen general.\nDetalles: {e}")


# main

async def mensaje_no_reconocido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comandos = (
        "⚙️ *Comandos disponibles:*\n"
        "/start — Inicia el bot\n"
        "/resumen [mes] — Gráfico pastel de gastos (mes actual por defecto)\n"
        "/resumen_general [año] — Gastos mensuales del año (año actual por defecto)\n"
        "/gastos — Gasto por proveedor\n\n"
        "💡 También podés enviar una *foto o PDF de una factura* para procesarla."
    )
    await update.message.reply_text(comandos, parse_mode="Markdown")


async def comando_desconocido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mensaje_no_reconocido(update, context)


if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

   
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gastos", gastos))
    app.add_handler(CommandHandler("resumen", resumen))
    app.add_handler(CommandHandler("resumen_general", resumen_general))

    
    app.add_handler(MessageHandler(filters.PHOTO, handle_invoice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"(?i)^\s*hola\s*$"), start))

    app.add_handler(MessageHandler(filters.COMMAND, comando_desconocido))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.Regex(r"(?i)^\s*hola\s*$"), mensaje_no_reconocido))

    app.run_polling()


