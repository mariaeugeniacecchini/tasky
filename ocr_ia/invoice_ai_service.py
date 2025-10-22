from flask import Flask, request, jsonify
from openai import OpenAI
import base64, io, os, json, re
from PIL import Image
import pdfplumber
import pytesseract
from pdf2image import convert_from_bytes
from datetime import datetime

app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# funciones de extracción
def extract_text_from_pdf(pdf_bytes):
    """Extrae texto directo (si el PDF tiene texto embebido)."""
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
    except Exception:
        text = ""
    return text.strip()


def extract_text_with_ocr(pdf_bytes):
    """Convierte PDF escaneado a imágenes y aplica OCR."""
    pages = convert_from_bytes(pdf_bytes)
    text = ""
    for page in pages:
        text += pytesseract.image_to_string(page, lang="spa")
    return text.strip()


def extract_ocr_text(image_bytes):
    """OCR general (PDF o imagen)."""
    try:
        if image_bytes[:4] == b"%PDF":
            pages = convert_from_bytes(image_bytes)
            text = ""
            for i, page in enumerate(pages):
                text += pytesseract.image_to_string(page, lang="spa") + "\n"
            return text.strip()
        else:
            image = Image.open(io.BytesIO(image_bytes))
            return pytesseract.image_to_string(image, lang="spa")
    except Exception as e:
        pass
        return ""


# normalización de datos
def normalizar_factura(data):
    """Limpia y valida campos comunes de la factura (fecha, total)."""
    try:
        
        fecha_valida = None
        if "fecha" in data and data["fecha"]:
            texto = str(data["fecha"]).strip()
            match = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", texto)
            if match:
                fecha_raw = match.group(1)
                formatos = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"]
                for fmt in formatos:
                    try:
                        f = datetime.strptime(fecha_raw, fmt)
                        if (
                            f.date() != datetime.now().date()
                            and 2000 <= f.year <= datetime.now().year
                            and f <= datetime.now()
                        ):
                            fecha_valida = f
                            break
                    except Exception:
                        continue

        if fecha_valida:
            data["fecha"] = fecha_valida.strftime("%d/%m/%Y")
        else:
            data["fecha"] = ""

        # normaliza el total
        if "total" in data and data["total"]:
            num = re.sub(r"[^\d,\.]", "", str(data["total"]))
            num = num.replace(",", ".")
            try:
                data["total"] = float(num)
            except Exception:
                data["total"] = 0.0

    except Exception as e:
        pass

    return data


def detectar_tipo_documento(texto):
    """Detecta si es una factura común o un comprobante de transferencia."""
    texto_lower = texto.lower()
    

    
    # indicadores específicos de transferencia bancaria
    indicadores_transferencia = [
        "comprobante de transferencia",
        "importe debitado",
        "cuenta destino", 
        "titular cuenta destino",
        "fecha de ejecución",
        "cuenta débito",
        "n° comprobante",
        "nro comprobante",
        "numero comprobante"
    ]
    
    # nombres específicos de bancos
    bancos = ["santander", "galicia", "bbva", "hsbc", "macro", "nación", "provincia"]
    
    # destinatarios conocidos que indican transferencia
    destinatarios_conocidos = [
        "menno gabriela alejandra",
        "menno gabriela",
        "grupo zafche", 
        "zafche s.a.",
        "cons ed mistica",
        "mistica calle",
        "calle 7 num 39",
        "ed mistica"
    ]
    
   
    coincidencias_transferencia = sum(1 for ind in indicadores_transferencia if ind in texto_lower)
    coincidencias_banco = sum(1 for banco in bancos if banco in texto_lower)
    coincidencias_destinatarios = sum(1 for dest in destinatarios_conocidos if dest in texto_lower)
    
    
    es_transferencia = (
        
        ("santander" in texto_lower and "comprobante" in texto_lower) or
        
        # reglas de respaldo
        ("comprobante de transferencia" in texto_lower) or
        ("importe debitado" in texto_lower) or
        ("cuenta destino" in texto_lower) or
        ("titular cuenta" in texto_lower) or
        
        # si menciona destinatarios específicos
        any(dest in texto_lower for dest in ["cons ed mistica", "menno gabriela", "grupo zafche"])
    )
    
    return "transferencia" if es_transferencia else "factura"

    
    return "transferencia" if es_transferencia else "factura"


def procesar_transferencia_bancaria(texto):
    """Procesa específicamente comprobantes de transferencias bancarias."""
    
    prompt_transferencia = """
ANÁLISIS DE TRANSFERENCIA BANCARIA

REGLA PRINCIPAL - IDENTIFICACIÓN DEL PROVEEDOR:
El PROVEEDOR es quien RECIBE el dinero, NO el banco que procesa la transferencia.

PROHIBIDO: "Santander", "Banco Santander", "Galicia", etc.
CORRECTO: El nombre exacto del "Titular cuenta destino"

CAMPOS A BUSCAR:
- "Titular cuenta destino" - ESE es el proveedor
- "Destinatario" - ESE es el proveedor  
- "Beneficiario" - ESE es el proveedor

CAMPOS A EXTRAER:
1. **proveedor**: EL NOMBRE EXACTO del titular de la cuenta destino
2. **fecha**: Busca "Fecha de ejecución" - formato DD/MM/YYYY  
3. **total**: Busca "Importe debitado" - convierte a número decimal
4. **items**: SIEMPRE: [{"nombre": "Transferencia bancaria", "precio": [TOTAL_NUMERICO]}]

PROHIBICIÓN ABSOLUTA SOBRE EL PROVEEDOR:
- NUNCA uses "Santander", "Galicia", "BBVA", etc. como proveedor
- El banco es quien HACE la transferencia, NO quien la recibe
- El proveedor SIEMPRE debe ser el "Titular cuenta destino"
- Busca la línea que dice "Titular cuenta destino" y usa ESE texto exacto

EJEMPLO CORRECTO:
- Si ves "Titular cuenta destino: Cons Ed Mistica Calle 7 Num 39"
- Entonces proveedor: "Cons Ed Mistica Calle 7 Num 39"
- NUNCA proveedor: "Santander"

5. **categoria**: Usa SOLO estas opciones:

CATEGORÍAS OBLIGATORIAS:
- Si titular contiene "Menno Gabriela" -> "Alquiler"  
- Si titular contiene "Grupo Zafche" -> "Alquiler"
- Si titular contiene "Cons Ed Mistica" -> "Expensas"
- Cualquier otro caso -> "Otros"

PROHIBICIONES:
- NUNCA uses "Servicios" 
- NUNCA uses "Facturas/Servicios"
- NUNCA inventes categorías

EJEMPLOS DE SALIDA CORRECTA:

Para "Menno Gabriela Alejandra":
{
  "proveedor": "Menno Gabriela Alejandra",
  "fecha": "03/10/2025",
  "total": 199968.00,
  "items": [{"nombre": "Transferencia bancaria", "precio": 199968.00}],
  "categoria": "Alquiler"
}

Para "Grupo Zafche S.a.":
{
  "proveedor": "Grupo Zafche S.a.", 
  "fecha": "03/10/2025",
  "total": 268560.00,
  "items": [{"nombre": "Transferencia bancaria", "precio": 268560.00}],
  "categoria": "Alquiler"
}

Para "Cons Ed Mistica Calle 7 Num 39":
{
  "proveedor": "Cons Ed Mistica Calle 7 Num 39",
  "fecha": "03/10/2025",
  "total": 14691.00,
  "items": [{"nombre": "Transferencia bancaria", "precio": 14691.00}],
  "categoria": "Expensas"
}

ANALIZA ESTE COMPROBANTE:
"""
    
    return prompt_transferencia + texto


# endpoint principal
@app.route("/process", methods=["POST"])
def process_invoice():
    try:
    
        if request.is_json and "data" in request.json:
            file_bytes = base64.b64decode(request.json["data"])
            filename = request.json.get("filename", "file")
        elif "file" in request.files:
            file = request.files["file"]
            file_bytes = file.read()
            filename = file.filename
        else:
            return jsonify({"error": "No se encontró ningún archivo"}), 400

        if not file_bytes:
            return jsonify({"error": "El archivo está vacío"}), 400

        # OCR previo
        ocr_text = extract_ocr_text(file_bytes)
        ocr_text = re.sub(r"\s+", " ", ocr_text)

        
        tipo_documento = detectar_tipo_documento(ocr_text)
        
        
        if tipo_documento == "transferencia":
            prompt = procesar_transferencia_bancaria(ocr_text)
        else:
            
            prompt = """
Analiza cuidadosamente la siguiente factura y devuelve los campos solicitados en formato JSON.

Tu tarea es **extraer información REAL del documento, no inventarla**.  
Si algún dato no aparece, debes dejar el campo vacío o null.

Campos requeridos:
- **proveedor**: nombre de la empresa o comercio emisor.
- **fecha**: la fecha de emisión de la factura (NO inventar ni usar la actual).
- **total**: el importe total (buscar palabras como 'TOTAL', 'TOTAL FINAL', 'IMPORTE A PAGAR', 'TOTAL FACTURA').
- **items**: lista de productos o conceptos, con nombre y precio (si están visibles).
- **categoria**: clasifica en una de estas:
  1. Supermercado
  2. Delivery (PedidosYa, Rappi)
  3. Petshop
  4. Farmacia
  5. Alquiler
  6. Expensas
  7. Otros
  8. Servicios

REGLAS IMPORTANTES:
- **No uses la fecha del día actual bajo ningún motivo.**
- **Si no estás seguro de la fecha, deja `"fecha": ""`.**
- Usa solo la fecha que esté junto a palabras como “Fecha”, “Emisión”, “Factura”, “Fecha de compra”.
- Ignora fechas de vencimiento o entrega.
- Devuelve **solo JSON válido**, sin texto adicional.
- Para el campo "total", prioriza el número junto a palabras como “TOTAL”, “TOTAL A PAGAR” o “IMPORTE FINAL”.
- Si el documento no tiene texto legible o el total no se entiende, deja el valor en cero.

Ejemplo de salida válida:
{
  "proveedor": "Carrefour",
  "fecha": "12/09/2024",
  "total": 4532.40,
  "items": [{"nombre": "Pan", "precio": 250.00}],
  "categoria": "Supermercado"
}
"""

        # procesamiento según tipo de archivo
        if tipo_documento == "transferencia":
            
            content = [{"type": "text", "text": prompt}]
        else:
            
            if filename.lower().endswith((".jpg", ".jpeg", ".png")):
                image_base64 = base64.b64encode(file_bytes).decode("utf-8")
                content = [
                    {"type": "text", "text": prompt + "\n\nTexto OCR extraído:\n" + ocr_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            elif filename.lower().endswith(".pdf"):
                text = extract_text_from_pdf(file_bytes)
                if not text or len(text) < 30:
                    text = extract_text_with_ocr(file_bytes)
                if not text:
                    return jsonify({"error": "No se pudo extraer texto del PDF"}), 400
                content = [{"type": "text", "text": f"{prompt}\n\nTexto de la factura:\n{text}"}]
            else:
                return jsonify({"error": "Formato de archivo no soportado"}), 400

        # llamada al modelo
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un analizador de facturas que devuelve JSON estructurado."},
                {"role": "user", "content": content}
            ],
            temperature=0.2,
        )

        # limpieza
        raw = response.choices[0].message.content.strip()
        clean = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()

        try:
            parsed = json.loads(clean)

            # anula fechas iguales a hoy o futuras
            if parsed.get("fecha"):
                fecha_str = str(parsed["fecha"]).strip()
                formatos = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"]
                for fmt in formatos:
                    try:
                        f = datetime.strptime(fecha_str, fmt)
                        if f.date() == datetime.now().date() or f.date() > datetime.now().date():
                            parsed["fecha"] = ""
                        break
                    except Exception:
                        continue

            
            parsed = normalizar_factura(parsed)

            #vuelve a verificar después de normalizar
            if parsed.get("fecha"):
                fecha_str = parsed["fecha"]
                for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"]:
                    try:
                        f = datetime.strptime(fecha_str, fmt)
                        if f.date() == datetime.now().date() or f > datetime.now():
                            parsed["fecha"] = ""
                        break
                    except Exception:
                        continue

            return jsonify(parsed), 200

        except Exception:
            return jsonify({"raw_response": raw}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
