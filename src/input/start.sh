#!/bin/sh

echo "Starting Flask Authentication Server..."
python /app/src/input/ideasoft_server_connection.py &

# Flask'in PID'sini kaydet
FLASK_PID=$!

# Flask'in tamamen açılması için bekle
sleep 5

# Eğer token.json varsa, izinlerini güncelle
TOKEN_FILE="/app/src/input/token.json"


if [ -f "$TOKEN_FILE" ]; then
    echo "Updating permissions for token.json"
    chmod 644 "$TOKEN_FILE"
fi


# Flask'i kapatma! Arka planda çalışsın
echo "Flask Server is running indefinitely..."
wait $FLASK_PID
