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
DATABASE_URL = "postgresql://mapbotuser:r47l5ou0pDueVnus4tiD3d2w7hYQJ1vy@dpg-db4fc5ks728c73ajgig0-a.frankfurt-postgres.render.com/mapbotdb"

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

init_db()

# УПРОЩЕННЫЙ ПОИСК (КАК У САМОКАТОВ)
def get_coordinates(address):
    query = f"Смоленск, {address}"
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
    
    # === СОЗДАТЬ ПАРКОВКУ ===
    if text_lower.startswith('создать p'):
        # Берем остаток из ОРИГИНАЛЬНОГО текста, чтобы сохранить регистр (Ермолино Центр)
        first_dash = text.find('-')
        if first_dash != -1:
            remainder = text[first_dash+1:].strip()
            if ' - ' in remainder:
                parts = remainder.split(' - ', 1)
                location_part = parts[0].strip()
                title = parts[1].strip() # Регистр сохранен!
                
                lat, lon = parse_coordinates(location_part)
                if lat is None:
                    bot.reply_to(message, f"⏳ Ищу в Смоленске: {location_part}...")
                    lat, lon = get_coordinates(location_part)
                    
                if lat and lon:
                    conn = get_db_connection()
                    c = conn.cursor()
                    try:
                        c.execute("INSERT INTO parkings (title, address, lat, lon) VALUES (%s, %s, %s, %s)", 
                                 (title, location_part, lat, lon))
                        conn.commit()
                        bot.reply_to(message, f"✅ Парковка \"{title}\" успешно добавлена!")
                    except psycopg.errors.UniqueViolation:
                        bot.reply_to(message, f"⚠️ Парковка \"{title}\" уже существует.")
                    conn.close()
                else:
                    bot.reply_to(message, f"❌ Не удалось найти: '{location_part}' в Смоленске.")
            else:
                bot.reply_to(message, "⚠️ Формат: Создать P - [Адрес] - [Название]")
        return

    # === УДАЛИТЬ ПАРКОВКУ ===
    if text_lower.startswith('удалить'):
        first_dash = text.find('-')
        if first_dash != -1:
            remainder = text[first_dash+1:].strip()
            # Пытаемся взять название (все, что после второго дефиса, или весь остаток)
            if ' - ' in remainder:
                parts = remainder.split(' - ', 1)
                title_to_delete = parts[1].strip()
            else:
                title_to_delete = remainder.strip()
                
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("DELETE FROM parkings WHERE title = %s", (title_to_delete,))
            conn.commit()
            if c.rowcount > 0:
                bot.reply_to(message, f"🗑️ Парковка \"{title_to_delete}\" удалена.")
            else:
                bot.reply_to(message, f"❌ Парковка \"{title_to_delete}\" не найдена.")
            conn.close()
        return

    # === САМОКАТЫ ===
    if '-' in text:
        parts = text.rsplit('-', 1) 
        location_part = parts[0].strip()
        title = parts[1].strip()
        
        lat, lon = parse_coordinates(location_part)
        if lat is None:
            bot.reply_to(message, f"⏳ Ищу в Смоленске: {location_part}...")
            lat, lon = get_coordinates(location_part)
            
        if lat and lon:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO points (title, address, lat, lon, status) VALUES (%s, %s, %s, %s, 'active')",
                     (title, location_part, lat, lon))
            conn.commit()
            conn.close()
            bot.reply_to(message, f"✅ Самокат '{title}' добавлен!")
        else:
            bot.reply_to(message, f"❌ Не удалось найти: '{location_part}' в Смоленске.")

# === API ЭНДПОИНТЫ ===
@app.route('/')
def serve_website():
    return "Бот работает!"

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
    conn = get_db_connection()
    c = conn.cursor()
    if data.get('status') == 'found':
        c.execute("DELETE FROM points WHERE id = %s", (data.get('id'),))
        c.execute("DELETE FROM departures WHERE point_id = %s", (data.get('id'),))
    else:
        c.execute("UPDATE points SET status = %s WHERE id = %s", (data.get('status'), data.get('id')))
        c.execute("DELETE FROM departures WHERE point_id = %s", (data.get('id'),))
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
    bot.polling(none_stop=True)

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
