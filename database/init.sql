CREATE TABLE proveedores (
  id SERIAL PRIMARY KEY,
  nombre TEXT UNIQUE NOT NULL
);

CREATE TABLE facturas (
  id SERIAL PRIMARY KEY,
  proveedor_id INT REFERENCES proveedores(id),
  numero TEXT,
  fecha DATE,
  moneda TEXT DEFAULT 'ARS',
  total NUMERIC(14,2),
  categoria VARCHAR(100),
  raw_json JSONB,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE marcas (
  id SERIAL PRIMARY KEY,
  nombre TEXT UNIQUE NOT NULL
);

CREATE TABLE tipos_articulo (
  id SERIAL PRIMARY KEY,
  nombre TEXT UNIQUE NOT NULL
);

CREATE TABLE items (
  id SERIAL PRIMARY KEY,
  factura_id INT REFERENCES facturas(id) ON DELETE CASCADE,
  descripcion TEXT,
  tipo_articulo_id INT REFERENCES tipos_articulo(id),
  marca_id INT REFERENCES marcas(id),
  cantidad NUMERIC(12,3),
  precio_unitario NUMERIC(14,2),
  precio_total NUMERIC(14,2)
);

CREATE VIEW v_resumen AS
SELECT
  date_trunc('month', f.fecha) AS mes,
  SUM(i.precio_total) AS gasto_mes
FROM facturas f
JOIN items i ON i.factura_id = f.id
GROUP BY 1
ORDER BY 1 DESC;

-- Logs de OCR (texto completo para análisis o debug)
CREATE TABLE IF NOT EXISTS logs_ocr (
    id SERIAL PRIMARY KEY,
    factura_id INT NULL REFERENCES facturas(id) ON DELETE SET NULL,
    proveedor_detectado VARCHAR(100),
    fecha TIMESTAMP DEFAULT NOW(),
    texto_ocr TEXT,
    fuente VARCHAR(50) DEFAULT 'ocr_ia'
);


