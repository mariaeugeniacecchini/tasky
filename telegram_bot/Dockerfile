FROM python:3.9.19-slim

WORKDIR /app
COPY . .

#Twemoji
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget ca-certificates fontconfig fonts-dejavu-core && \
    mkdir -p /app/assets/emojis && \
    echo "📦 Descargando emojis Twemoji..." && \
    wget -q -O /app/assets/emojis/pill.png   https://github.com/twitter/twemoji/raw/master/assets/72x72/1f48a.png && \
    wget -q -O /app/assets/emojis/burger.png https://github.com/twitter/twemoji/raw/master/assets/72x72/1f354.png && \
    wget -q -O /app/assets/emojis/cart.png   https://github.com/twitter/twemoji/raw/master/assets/72x72/1f6d2.png && \
    wget -q -O /app/assets/emojis/gear.png   https://github.com/twitter/twemoji/raw/master/assets/72x72/2699.png && \
    wget -q -O /app/assets/emojis/box.png    https://github.com/twitter/twemoji/raw/master/assets/72x72/1f4e6.png && \
    wget -q -O /app/assets/emojis/cat.png    https://github.com/twitter/twemoji/raw/master/assets/72x72/1f408.png && \
    echo "✅ Emojis descargados:" && ls -l /app/assets/emojis && \
    apt-get clean && rm -rf /var/lib/apt/lists/*


RUN pip install --no-cache-dir -r requirements.txt \
    matplotlib numpy Pillow psycopg2-binary requests python-telegram-bot==20.7

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
EXPOSE 5000
CMD ["python", "main.py"]



