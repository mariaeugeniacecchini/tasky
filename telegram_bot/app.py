from flask import Flask, request, jsonify
import io

app = Flask(__name__)

@app.route('/process', methods=['POST'])
def process_invoice():
    if 'data' not in request.files:
        return jsonify({'error': 'No se envió ningún archivo'}), 400

    file = request.files['data']
    # 👇 Aquí iría tu lógica de IA (por ahora simulamos la respuesta)
    text = "Factura procesada correctamente 🧾✅"

    return jsonify({'texto': text}), 200

if __name__ == '__main__':
    # Escucha en todas las interfaces, puerto 5000
    app.run(host='0.0.0.0', port=5000)

