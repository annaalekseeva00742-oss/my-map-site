import telebot
import requests
import sqlite3
from flask import Flask, jsonify, request
from flask_cors import CORS
import threading
import os

# ⚠️ ВАЖНО: Вставьте сюда НОВЫЙ токен, который выдал BotFather после отзыва старого!
BOT_TOKEN = "8803648566:AAHmG4XTMTDqfIHlWjBeDsKCGmQ18pxKnGQ" 
ADMIN_CHAT_ID = 7929131842 # Ваш ID, чтобы только вы могли управлять ботом

app = Flask(__name__)
CORS(app) # Разрешаем сайту обращаться к боту

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect('points.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS points
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT, address TEXT, lat REAL, lon REAL, status TEXT DEFAULT 'active')''')
    conn.commit()
    conn.close()

init_db()

# === ГЕОКОДЕР (Бесплатный OpenStreetMap) ===
def get_coordinates(address):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1}
    headers = {"User-Agent": "MyTelegramBot/1.0"}
    response = requests.get(url, params=params, headers=headers)
    data = response.json()
    if data:
        return float(data[0]["lat"]), float(data[0]["lon"])
    return None, None

# === ТЕЛЕГРАМ БОТ ===
bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    # Проверяем, что пишет только владелец
    if message.chat.id != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ У вас нет доступа к этому боту.")
        return

    text = message.text.strip()
    if ' - ' in text:
        parts = text.split(' - ', 1)
        address = parts[0].strip()
        title = parts[1].strip()
        
        lat, lon = get_coordinates(address)
        
        if lat and lon:
            conn = sqlite3.connect('points.db')
            c = conn.cursor()
            c.execute("INSERT INTO points (title, address, lat, lon, status) VALUES (?, ?, ?, ?, 'active')",
                     (title, address, lat, lon))
            conn.commit()
            conn.close()
            bot.reply_to(message, f"✅ Точка добавлена!\n📍 {title}\n🏠 {address}")
        else:
            bot.reply_to(message, "❌ Не удалось найти адрес. Проверьте написание.")
    else:
        bot.reply_to(message, "⚠️ Формат: адрес - название\nПример: ул Гагарина 1 - 655")

# === API ДЛЯ САЙТА ===
@app.route('/get_points')
def get_points():
    conn = sqlite3.connect('points.db')
    c = conn.cursor()
    # Сайт получает только те точки, которые не "найдены"
    c.execute("SELECT id, title, address, lat, lon, status FROM points WHERE status != 'found'")
    points = [{"id": row[0], "title": row[1], "address": row[2], "lat": row[3], "lon": row[4], "status": row[5]} 
              for row in c.fetchall()]
    conn.close()
    return jsonify(points)

@app.route('/update_status', methods=['POST'])
def update_status():
    data = request.json
    point_id = data.get('id')
    status = data.get('status')
    
    conn = sqlite3.connect('points.db')
    c = conn.cursor()
    if status == 'found':
        c.execute("DELETE FROM points WHERE id = ?", (point_id,))
    else:
        c.execute("UPDATE points SET status = ? WHERE id = ?", (status, point_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# === ЗАПУСК ===
def run_bot():
    bot.polling(none_stop=True)

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)