FROM python:3.9.19-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt matplotlib numpy

COPY entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]

EXPOSE 5000
CMD ["python", "invoice_ai_service.py"]



