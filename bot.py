import telebot
import requests
import re
import os
import psycopg2
from flask import Flask, jsonify, request
from flask_cors import CORS
import threading

# BOT_TOKEN = os.environ.get("BOT_TOKEN")  <-- Эта строка теперь отключена
BOT_TOKEN = "8803648566:AAHmG4XTMTDqfIHlWjBeDsKCGmQ18pxKnGQ"
ADMIN_CHAT_ID = 7929131842
DATABASE_URL = os.environ.get("postgresql://mapbotuser:r47l5ou0pDueVnus4tiD3d2w7hYQJ1vy@dpg-db4fc5ks728c73ajgig0-a.frankfurt-postgres.render.com/mapbotdb")

app = Flask(__name__)
CORS(app)

# Функция для получения подключения к БД
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # Создаем таблицу точек (SERIAL - это автоинкремент в PostgreSQL)
    c.execute('''CREATE TABLE IF NOT EXISTS points
                 (id SERIAL PRIMARY KEY,
                  title TEXT, address TEXT, lat REAL, lon REAL, status TEXT DEFAULT 'active')''')
    # Создаем таблицу выездов
    c.execute('''CREATE TABLE IF NOT EXISTS departures
                 (point_id INTEGER PRIMARY KEY,
                  point_title TEXT,
                  person_name TEXT)''')
    conn.commit()
    conn.close()

# Инициализируем таблицы при запуске
init_db()

def get_coordinates(address):
    address_clean = address.strip()
    street_prefixes = ('ул.', 'улица', 'пр.', 'проспект', 'пл.', 'площадь', 'пер.', 'переулок', 'ш.', 'шоссе', 'б-р', 'бульвар', 'наб.', 'набережная')
    
    if not address_clean.lower().startswith(street_prefixes):
        address_clean = "улица " + address_clean
    
    query = f"г. Смоленск, {address_clean}"
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "json", "limit": 1}
    headers = {"User-Agent": "SmolenskMapBot/1.0"}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        data = response.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except:
        pass
    return None, None

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.chat.id != ADMIN_CHAT_ID or message.text is None:
        return 

    text = message.text.strip()
    
    if '-' in text:
        parts = text.rsplit('-', 1) 
        location_part = parts[0].strip()
        title = parts[1].strip()
        
        if not location_part or not title:
            bot.reply_to(message, "⚠️ Формат: Адрес или Координаты - Название\nПример: Ленина 14 - 666")
            return

        coord_match = re.match(r'^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$', location_part)
        
        if coord_match:
            lat = float(coord_match.group(1))
            lon = float(coord_match.group(2))
            bot.reply_to(message, f"✅ Координаты приняты!\n📍 {title}")
        else:
            bot.reply_to(message, f"⏳ Ищу: г. Смоленск, {location_part}...")
            lat, lon = get_coordinates(location_part)
            
        if lat and lon:
            conn = get_db_connection()
            c = conn.cursor()
            # В PostgreSQL используем %s вместо ?
            c.execute("INSERT INTO points (title, address, lat, lon, status) VALUES (%s, %s, %s, %s, 'active')",
                     (title, location_part, lat, lon))
            conn.commit()
            conn.close()
            bot.reply_to(message, f"✅ Точка '{title}' успешно добавлена на карту!")
        else:
            bot.reply_to(message, f"❌ Не удалось найти адрес: '{location_part}' в Смоленске.")
    else:
        bot.reply_to(message, "⚠️ Формат: Адрес или Координаты - Название\nПримеры:\n• Ленина 14 - 666\n• ул. Гагарина 5 - Офис")

@app.route('/')
def serve_website():
    return "Бот работает! API доступно."

@app.route('/get_points')
def get_points():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, title, address, lat, lon, status FROM points WHERE status != 'found'")
    points = [{"id": row[0], "title": row[1], "address": row[2], "lat": row[3], "lon": row[4], "status": row[5]} for row in c.fetchall()]
    conn.close()
    return jsonify(points)

@app.route('/update_status', methods=['POST'])
def update_status():
    data = request.json
    point_id = data.get('id')
    status = data.get('status')
    conn = get_db_connection()
    c = conn.cursor()
    if status == 'found':
        c.execute("DELETE FROM points WHERE id = %s", (point_id,))
        c.execute("DELETE FROM departures WHERE point_id = %s", (point_id,))
    else:
        c.execute("UPDATE points SET status = %s WHERE id = %s", (status, point_id))
        c.execute("DELETE FROM departures WHERE point_id = %s", (point_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/get_departures')
def get_departures():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT point_id, point_title, person_name FROM departures")
    departures = [{"point_id": row[0], "point_title": row[1], "person_name": row[2]} for row in c.fetchall()]
    conn.close()
    return jsonify(departures)

@app.route('/add_departure', methods=['POST'])
def add_departure():
    data = request.json
    point_id = data.get('point_id')
    point_title = data.get('point_title')
    person_name = data.get('person_name')
    
    conn = get_db_connection()
    c = conn.cursor()
    # ON CONFLICT делает "upsert" (обновляет, если точка уже есть)
    c.execute("""INSERT INTO departures (point_id, point_title, person_name) 
                 VALUES (%s, %s, %s) 
                 ON CONFLICT (point_id) 
                 DO UPDATE SET point_title = EXCLUDED.point_title, person_name = EXCLUDED.person_name""",
             (point_id, point_title, person_name))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/remove_departure', methods=['POST'])
def remove_departure():
    data = request.json
    point_id = data.get('point_id')
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM departures WHERE point_id = %s", (point_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/clear_all_departures', methods=['POST'])
def clear_all_departures():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM departures")
    conn.commit()
    conn.close()
    return jsonify({"success": True})

def run_bot():
    bot.polling(none_stop=True)

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
