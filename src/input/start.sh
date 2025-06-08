#!/bin/sh

echo "🚀 Starting Flask Authentication Server..."
python /app/src/input/ideasoft_server_connection.py &

# Flask'in PID'sini kaydet
FLASK_PID=$!

# Sağlık kontrolü için bekle
echo "⏳ Flask'in tamamen açılması bekleniyor..."
while ! curl -s http://127.0.0.1:5001/health > /dev/null; do
  sleep 2
done

echo "✅ Flask başarıyla başlatıldı!"

# Eğer token.json varsa, izinlerini güncelle
TOKEN_FILE="/app/src/input/token.json"

if [ -f "$TOKEN_FILE" ]; then
    echo "🔄 Updating permissions for token.json"
    chmod 644 "$TOKEN_FILE"
fi

echo "✅ Flask Server is running indefinitely..."
wait $FLASK_PID