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


# VALIDACIONES DE ARRANQUE

if not BOT_TOKEN:
    raise SystemExit("⚠️ ERROR: No se encontró TELEGRAM_TOKEN en las variables de entorno (.env).")




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





async def process_invoice_file(update: Update, file_path: str, file_name: str, mime_type: str):
    try:
        # Enviar archivo al servicio OCR
        response = requests.post(OCR_URL, files={"file": (file_name, open(file_path, "rb"), mime_type)})
        print(f"📥 Respuesta OCR ({mime_type}): {response.status_code}")

        if response.status_code != 200:
            await update.message.reply_text("❌ Error al procesar la factura (OCR no respondió correctamente).")
            return

        data = response.json()
        print("🧾 OCR data:", data)

        # Validaciones básicas
        if not all(k in data for k in ("proveedor", "fecha", "total", "categoria")):
            await update.message.reply_text("⚠️ La respuesta del OCR está incompleta.")
            return

        proveedor = data["proveedor"].strip()
        categoria = data.get("categoria", "Otros")

        # --- Parsear fecha y total ---
        fecha = parse_fecha_o_none(data.get("fecha"))
        try:
            total = float(str(data.get("total", 0)).replace(",", "."))
        except Exception:
            total = 0.0

        cursor = conn.cursor()

        # Insertar o reutilizar proveedor
        cursor.execute("""
            INSERT INTO proveedores (nombre)
            VALUES (%s)
            ON CONFLICT (nombre) DO UPDATE SET nombre = EXCLUDED.nombre
            RETURNING id;
        """, (proveedor,))
        proveedor_id = cursor.fetchone()[0]

        # Evitar duplicados (maneja NULL en fecha)
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
                f"⚠️ La factura de {proveedor} {fecha_texto} ya está registrada."
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
        print("❌ Error en process_invoice_file:")
        traceback.print_exc()
        await update.message.reply_text(f"⚠️ Error al procesar la factura.\nDetalles: {e}")


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
        print("❌ Error en handle_invoice:")
        traceback.print_exc()
        await update.message.reply_text(f"⚠️ Error al procesar la imagen.\nDetalles: {e}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        document = update.message.document
        if not document.mime_type.startswith("application/pdf"):
            await update.message.reply_text("⚠️ Solo se admiten archivos PDF.")
            return

        file = await document.get_file()
        file_path = f"/tmp/{document.file_name}"
        await file.download_to_drive(file_path)
        await process_invoice_file(update, file_path, document.file_name, "application/pdf")
    except Exception as e:
        import traceback
        print(" Error en handle_document:")
        traceback.print_exc()
        await update.message.reply_text(f" Error al procesar el PDF.\nDetalles: {e}")




# COMANDOS

async def promedio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cursor = conn.cursor()

        args = context.args
        if args:
            mes_nombre = args[0].capitalize()
            meses = {
                "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
                "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
            }
            mes_num = meses.get(mes_nombre)
            if not mes_num:
                await update.message.reply_text("Mes no válido. Ejemplo: /promedio Septiembre")
                cursor.close()
                return
        else:
            cursor.execute("SELECT EXTRACT(MONTH FROM fecha) FROM facturas ORDER BY fecha DESC LIMIT 1;")
            mes_num = cursor.fetchone()[0]

        cursor.execute("""
            SELECT AVG(gasto_mes) 
            FROM v_resumen 
            WHERE EXTRACT(MONTH FROM mes) = %s;
        """, (mes_num,))
        promedio_mensual = cursor.fetchone()[0]
        cursor.close()

        if promedio_mensual:
            await update.message.reply_text(
                f"📊 Promedio de gasto para el mes {mes_nombre if args else 'actual'}: ${promedio_mensual:,.2f}"
            )
        else:
            await update.message.reply_text("No hay datos suficientes para calcular el promedio de ese mes.")
    except Exception as e:
        print(f" Error en /promedio: {e}")
        await update.message.reply_text(" Error al calcular el promedio mensual.")


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

        # Analizar argumentos (pueden venir en cualquier orden)
        args = [a.capitalize() for a in context.args] if context.args else []

        meses = {
            "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
            "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10,
            "Noviembre": 11, "Diciembre": 12
        }

       
        mes_nombre = None
        categoria_filtro = None
        for arg in args:
            if arg in meses:
                mes_nombre = arg
            else:
                categoria_filtro = arg

        
        if mes_nombre:
            mes_num = meses[mes_nombre]
        else:
            cursor.execute("SELECT EXTRACT(MONTH FROM fecha) FROM facturas ORDER BY fecha DESC LIMIT 1;")
            mes_num = cursor.fetchone()[0]
            mes_nombre = list(meses.keys())[int(mes_num) - 1]

        
        query_base = """
            SELECT COUNT(*), SUM(total), AVG(total)
            FROM facturas
            WHERE EXTRACT(MONTH FROM fecha) = %s
        """
        params = [mes_num]

        if categoria_filtro:
            query_base += " AND LOWER(categoria) LIKE LOWER(%s)"
            params.append(f"%{categoria_filtro}%")

        cursor.execute(query_base, params)
        count, total, avg = cursor.fetchone()

        
        query_items = """
            SELECT SUM(i.precio_total)
            FROM facturas f
            JOIN items i ON i.factura_id = f.id
            WHERE EXTRACT(MONTH FROM f.fecha) = %s
        """
        params_items = [mes_num]
        if categoria_filtro:
            query_items += " AND LOWER(f.categoria) LIKE LOWER(%s)"
            params_items.append(f"%{categoria_filtro}%")

        cursor.execute(query_items, params_items)
        gasto_mes = cursor.fetchone()[0] or 0

        
        categorias = []
        if not categoria_filtro:
            cursor.execute("""
                SELECT categoria, SUM(total)
                FROM facturas
                WHERE EXTRACT(MONTH FROM fecha) = %s
                GROUP BY categoria
                ORDER BY SUM(total) DESC;
            """, (mes_num,))
            categorias = cursor.fetchall()

        cursor.close()

        if count > 0:
            texto = f"📋 *Resumen de {mes_nombre}*"
            if categoria_filtro:
                texto += f" — categoría *{categoria_filtro}*\n"
            else:
                texto += ":\n"

            texto += (
                f"🧾 Facturas registradas: {count}\n"
                f"💵 Total gastado: ${total:,.2f}\n"
                f"📊 Promedio por factura: ${avg:,.2f}\n"
                f"📅 *Gasto total de ítems:* ${gasto_mes:,.2f}\n"
            )

            if categorias:
                texto += "\n📂 *Gasto por categoría:*\n"
                emojis = {
                    "Supermercado": "🛒",
                    "Delivery": "🍔",
                    "Petshop": "🐈",
                    "Farmacia": "💊",
                    "Otros": "📦",
                    "Servicios": "📄"
                }
                for categoria, suma in categorias:
                    emoji = emojis.get(categoria, "📦")
                    texto += f"{emoji} {categoria}: ${suma:,.2f}\n"

            await update.message.reply_text(texto, parse_mode="Markdown")
        else:
            if categoria_filtro:
                await update.message.reply_text(f" No hay facturas registradas para la categoría '{categoria_filtro}' en {mes_nombre}.")
            else:
                await update.message.reply_text(f"No hay facturas registradas para {mes_nombre}.")
    except Exception as e:
        print(f" Error en /resumen: {e}")
        await update.message.reply_text(" Error al generar el resumen mensual.")


async def resumen_general(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        import numpy as np
        import matplotlib.pyplot as plt
        from io import BytesIO
        from decimal import Decimal

        cursor = conn.cursor()

        # 🗓️ Soporta /resumen_general <mes>
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
                await update.message.reply_text("⚠️ Mes no válido. Ejemplo: /resumen_general Octubre")
                cursor.close()
                return
        else:
            cursor.execute("SELECT EXTRACT(MONTH FROM fecha) FROM facturas ORDER BY fecha DESC LIMIT 1;")
            mes_num = int(cursor.fetchone()[0])
            mes_nombre = [k for k, v in meses.items() if v == mes_num][0]

        # 📊 Totales por categoría
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
            await update.message.reply_text(f"⚠️ No hay facturas registradas para {mes_nombre}.")
            return

        # Normalizar categorías (ajustar nombre "Comida/Supermercado" → "Supermercado")
        categorias = []
        valores = []
        for cat, val in rows:
            if cat.lower() in ["comida/supermercado", "supermercado"]:
                cat = "Supermercado"
            categorias.append(cat)
            valores.append(float(val) if isinstance(val, (Decimal, float, int)) else 0.0)

        total = float(sum(valores))

        # 🎨 Colores
        colores = ["#FF6B6B", "#FFD93D", "#6BCB77", "#4D96FF", "#C77DFF", "#FF9CEE"][:len(valores)]

        # --- Crear figura principal ---
        fig, ax = plt.subplots(figsize=(6.5, 6.5), dpi=200)

        wedges, _ = ax.pie(
            valores,
            startangle=90,
            colors=colores,
            wedgeprops=dict(width=0.4, edgecolor="white")
        )

        # Total en el centro
        ax.text(
            0, 0, f"${total:,.0f}",
            ha="center", va="center",
            fontsize=22, fontweight="bold", color="#222"
        )

        # ✅ Porcentajes más pegados al color
        for i, (wedge, valor) in enumerate(zip(wedges, valores)):
            ang = (wedge.theta2 + wedge.theta1) / 2
            ang_rad = np.deg2rad(ang)
            x = 0.9 * np.cos(ang_rad)
            y = 0.9 * np.sin(ang_rad)
            porcentaje = (valor / total) * 100 if total > 0 else 0

            ax.text(
                x, y,
                f"{porcentaje:.1f}%",
                ha="center", va="center",
                fontsize=11,
                color="black",
                fontweight="bold"
            )

        # Título
        ax.set_title(
            f"Gastos por categoría — {mes_nombre}",
            fontsize=15,
            fontweight="bold",
            pad=20
        )

        # Leyenda simple (solo texto + color)
        ax.legend(
            wedges,
            categorias,
            title="Categorías",
            loc="lower center",
            bbox_to_anchor=(0.5, -0.2),
            fontsize=10.5,
            title_fontsize=11,
            ncol=2,
            frameon=False
        )

        fig.patch.set_facecolor("white")
        plt.tight_layout()

        # Guardar imagen
        buffer = BytesIO()
        plt.savefig(buffer, format="png", bbox_inches="tight", dpi=200)
        buffer.seek(0)
        plt.close(fig)

        # Enviar gráfico
        await update.message.reply_photo(photo=InputFile(buffer, filename=f"resumen_{mes_nombre}.png"))

        # 🧾 Detalle textual con emojis correctos
        emoji_map = {
            "Farmacia": "💊",
            "Delivery": "🍔",
            "Supermercado": "🛒",
            "Facturas/Servicios": "📄",
            "Servicios": "📄",
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
        print(" Error en /resumen_general:")
        traceback.print_exc()
        await update.message.reply_text(f" Error al generar el resumen general.\nDetalles: {e}")





# MAIN

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("promedio", promedio))
    app.add_handler(CommandHandler("gastos", gastos))
    app.add_handler(CommandHandler("resumen", resumen))
    app.add_handler(CommandHandler("resumen_general", resumen_general))
    app.add_handler(MessageHandler(filters.PHOTO, handle_invoice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    
    app.run_polling()