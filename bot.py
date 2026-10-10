import telebot
import requests
import re
import os
import psycopg
from flask import Flask, jsonify, request
from flask_cors import CORS
import threading

# BOT_TOKEN = os.environ.get("BOT_TOKEN")  <-- Эта строка теперь отключена
BOT_TOKEN = "8803648566:AAHdzjrUA2lRpnrUt1AFfY8w-U3WJKFwb9Q"
ADMIN_CHAT_ID = 7929131842
DATABASE_URL = os.environ.get("postgresql://mapbotuser:r47l5ou0pDueVnus4tiD3d2w7hYQJ1vy@dpg-db4fc5ks728c73ajgig0-a.frankfurt-postgres.render.com/mapbotdb")

print(f"🚀 Бот запускается. DATABASE_URL получен: {bool(DATABASE_URL)}")

app = Flask(__name__)
CORS(app)

def get_db_connection():
    return psycopg.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS points
                 (id SERIAL PRIMARY KEY, title TEXT, address TEXT, lat REAL, lon REAL, status TEXT DEFAULT 'active')''')
    c.execute('''CREATE TABLE IF NOT EXISTS departures
                 (point_id INTEGER PRIMARY KEY, point_title TEXT, person_name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS parkings
                 (id SERIAL PRIMARY KEY, title TEXT UNIQUE, address TEXT, lat REAL, lon REAL, 
                  available_count TEXT DEFAULT '?', dead_count TEXT DEFAULT '?')''')
    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")

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

def parse_coordinates(text):
    coord_match = re.match(r'^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$', text)
    if coord_match:
        return float(coord_match.group(1)), float(coord_match.group(2))
    return None, None

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.chat.id != ADMIN_CHAT_ID or message.text is None:
        return 

    text = message.text.strip()
    text_lower = text.lower()
    
    print(f"📩 Получено сообщение: '{text}'")
    
    if text_lower.startswith('создать p'):
        print("🅿️ Распознана команда: СОЗДАТЬ ПАРКОВКУ")
        remainder = text_lower[len('создать p'):].strip()
        if not remainder.startswith('-'):
            bot.reply_to(message, "⚠️ Формат: Создать P - [Адрес] - [Название]\nПример: Создать P - Ленина 14 - Парковка Центр")
            return
        remainder = remainder[1:].strip()
        if ' - ' not in remainder:
            bot.reply_to(message, "⚠️ Формат: Создать P - [Адрес] - [Название]\nПример: Создать P - 54.777, 32.052 - Ермолино Центр")
            return
        parts = remainder.split(' - ', 1)
        location_part = parts[0].strip()
        title = parts[1].strip()
        print(f" Адрес/координаты: '{location_part}', Название: '{title}'")
        if not location_part or not title:
            bot.reply_to(message, "⚠️ Пустые поля. Формат: Создать P - [Адрес] - [Название]")
            return
        lat, lon = parse_coordinates(location_part)
        if lat is None:
            bot.reply_to(message, f"⏳ Ищу: г. Смоленск, {location_part}...")
            lat, lon = get_coordinates(location_part)
        else:
            print(f"✅ Распознаны координаты: {lat}, {lon}")
        if lat and lon:
            conn = get_db_connection()
            c = conn.cursor()
            try:
                c.execute("INSERT INTO parkings (title, address, lat, lon) VALUES (%s, %s, %s, %s)", 
                         (title, location_part, lat, lon))
                conn.commit()
                bot.reply_to(message, f"✅ Парковка '{title}' успешно добавлена!")
                print(f"✅ Парковка '{title}' добавлена в БД")
            except psycopg.errors.UniqueViolation:
                bot.reply_to(message, f"⚠️ Парковка с названием '{title}' уже существует.")
            conn.close()
        else:
            bot.reply_to(message, f"❌ Не удалось найти: '{location_part}' в Смоленске.")
        return

    if text_lower.startswith('удалить p'):
        print("🗑️ Распознана команда: УДАЛИТЬ ПАРКОВКУ")
        remainder = text_lower[len('удалить p'):].strip()
        if not remainder.startswith('-'):
            bot.reply_to(message, "⚠️ Формат: Удалить P - [Название]")
            return
        title = remainder[1:].strip()
        if not title:
            bot.reply_to(message, "⚠️ Пустое название. Формат: Удалить P - [Название]")
            return
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM parkings WHERE title = %s", (title,))
        conn.commit()
        if c.rowcount > 0:
            bot.reply_to(message, f"🗑️ Парковка '{title}' удалена.")
        else:
            bot.reply_to(message, f"❌ Парковка '{title}' не найдена.")
        conn.close()
        return

    if '-' in text:
        print(" Распознана команда: САМОКАТ")
        parts = text.rsplit('-', 1) 
        location_part = parts[0].strip()
        title = parts[1].strip()
        if not location_part or not title:
            bot.reply_to(message, "⚠️ Формат: Адрес - Название\nПример: Ленина 14 - 666")
            return
        lat, lon = parse_coordinates(location_part)
        if lat is None:
            bot.reply_to(message, f" Ищу: г. Смоленск, {location_part}...")
            lat, lon = get_coordinates(location_part)
        if lat and lon:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO points (title, address, lat, lon, status) VALUES (%s, %s, %s, %s, 'active')",
                     (title, location_part, lat, lon))
            conn.commit()
            conn.close()
            bot.reply_to(message, f"✅ Точка '{title}' успешно добавлена на карту!")
        else:
            bot.reply_to(message, f"❌ Не удалось найти: '{location_part}' в Смоленске.")
    else:
        bot.reply_to(message, "️ Неизвестная команда.\n\nФорматы:\n• Самокат: Адрес - Название\n• Парковка: Создать P - Адрес - Название\n• Удалить: Удалить P - Название")

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
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""INSERT INTO departures (point_id, point_title, person_name) VALUES (%s, %s, %s) 
                 ON CONFLICT (point_id) DO UPDATE SET point_title = EXCLUDED.point_title, person_name = EXCLUDED.person_name""",
             (data.get('point_id'), data.get('point_title'), data.get('person_name')))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/remove_departure', methods=['POST'])
def remove_departure():
    data = request.json
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM departures WHERE point_id = %s", (data.get('point_id'),))
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

@app.route('/get_parkings')
def get_parkings():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, title, address, lat, lon, available_count, dead_count FROM parkings")
    parkings = [{"id": row[0], "title": row[1], "address": row[2], "lat": row[3], "lon": row[4], "available": row[5], "dead": row[6]} for row in c.fetchall()]
    conn.close()
    return jsonify(parkings)

@app.route('/update_parking', methods=['POST'])
def update_parking():
    data = request.json
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE parkings SET available_count = %s, dead_count = %s WHERE id = %s", 
              (data.get('available'), data.get('dead'), data.get('id')))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

def run_bot():
    print("🤖 Бот запущен и слушает сообщения...")
    bot.polling(none_stop=True)

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    port = int(os.environ.get("PORT", 8080))
    print(f" Веб-сервер запущен на порту {port}")
    app.run(host='0.0.0.0', port=port)
