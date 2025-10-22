import asyncio
import logging
import json
import requests
import sqlite3
import os
from bs4 import BeautifulSoup
from datetime import datetime
from flask import Flask, request
from threading import Thread
import time

# Конфигурация
URL = "https://hcdinamo.by/tickets/"
BOT_TOKEN = "8416784515:AAG1yGWcgm9gGFPJLodfLvEJrtmIFVJjsu8"
STATE_FILE = "matches_state.json"
CHECK_INTERVAL = 300
PING_INTERVAL = 240
ADMIN_ID = "645388044"

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt='%Y-%m-%d %H:%M:%S'
)

app = Flask(__name__)

# ========== КРАСИВЫЕ УВЕДОМЛЕНИЯ ==========

def format_beautiful_date(date_string):
    """Красивое форматирование даты матча"""
    try:
        # Пример: "22 17:00" -> "22 октября 2025 17:00"
        parts = date_string.split()
        if len(parts) >= 2:
            day = parts[0]
            time = parts[1]
            
            # Получаем текущий год и месяц
            current_year = datetime.now().year
            current_month = datetime.now().month
            months_ru = [
                'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
            ]
            month_name = months_ru[current_month - 1]
            
            return f"🗓 {day} {month_name} {current_year} ⏰ {time}"
        
        return f"📅 {date_string}"
    except Exception as e:
        logging.error(f"❌ Ошибка форматирования даты: {e}")
        return f"📅 {date_string}"

def create_beautiful_message(match):
    """Создание красивого сообщения о матче"""
    beautiful_date = format_beautiful_date(match["date"])
    
    # Разделяем название матча для лучшего отображения
    title = match['title']
    if ' — ' in title:
        home_team, away_team = title.split(' — ')
        formatted_title = f"🏒 {home_team} vs {away_team}"
        
        # Определяем тип матча (домашний/выездной)
        if 'Динамо-Минск' in title:
            if title.startswith('Динамо-Минск'):
                match_type = "🏠 Домашний матч"
            else:
                match_type = "✈️ Выездной матч"
        else:
            match_type = "🏒 Хоккейный матч"
    else:
        formatted_title = f"🏒 {title}"
        match_type = "🏒 Хоккейный матч"
    
    message = (
        "🔔 <b>НОВЫЙ МАТЧ В ПРОДАЖЕ!</b>\n\n"
        f"{formatted_title}\n"
        f"{match_type}\n"
        f"{beautiful_date}\n\n"
        f"🎟 <a href='{match['url']}'>Купить билеты</a>\n\n"
        "⚡️ <i>Успей забронировать лучшие места!</i>"
    )
    return message

def create_removed_message(match):
    """Создание сообщения об удаленном матче"""
    beautiful_date = format_beautiful_date(match["date"])
    
    title = match['title']
    if ' — ' in title:
        home_team, away_team = title.split(' — ')
        formatted_title = f"🏒 {home_team} vs {away_team}"
    else:
        formatted_title = f"🏒 {title}"
    
    message = (
        "❌ <b>МАТЧ УДАЛЕН ИЗ ПРОДАЖИ!</b>\n\n"
        f"{formatted_title}\n"
        f"{beautiful_date}\n\n"
        "😔 <i>Билеты больше не доступны</i>"
    )
    return message

# ========== АВТО-ПИНГ СИСТЕМА ==========

def start_ping_service():
    """Фоновая служба для пинга самого себя"""
    def ping_loop():
        service_url = "https://hockey-monitor.onrender.com/health"
        while True:
            try:
                response = requests.get(service_url, timeout=10)
                logging.info(f"🏓 Авто-пинг: {response.status_code}")
            except Exception as e:
                logging.error(f"❌ Ошибка авто-пинга: {e}")
            time.sleep(PING_INTERVAL)
    
    ping_thread = Thread(target=ping_loop, daemon=True)
    ping_thread.start()
    logging.info("🔔 Служба авто-пинга запущена")

# ========== WEB ЭНДПОИНТЫ ДЛЯ ОТЛАДКИ ==========

@app.route('/')
def home():
    return "🏒 Hockey Monitor Bot is running!"

@app.route('/health')
def health():
    return {"status": "running", "timestamp": datetime.now().isoformat()}

@app.route('/debug')
def debug():
    """Страница отладки"""
    subscribers = load_subscribers()
    
    html = f"""
    <html>
        <head><title>Debug Info</title><meta charset="utf-8"></head>
        <body>
            <h1>🏒 Debug Information</h1>
            <h2>👥 Подписчики:</h2>
            <ul>
    """
    
    for sub in subscribers:
        html += f"<li><b>{sub}</b> {'(ADMIN)' if sub == ADMIN_ID else ''}</li>"
    
    html += f"""
            </ul>
            <p><b>Всего подписчиков:</b> {len(subscribers)}</p>
            <p><b>ADMIN_ID:</b> {ADMIN_ID}</p>
            <hr>
            <p><a href="/test_send_all">📤 Тестовая отправка всем</a></p>
            <p><a href="/subscribers">📋 Список подписчиков (JSON)</a></p>
        </body>
    </html>
    """
    
    return html

@app.route('/test_send_all')
def test_send_all():
    """Тестовая отправка всем подписчикам"""
    subscribers = load_subscribers()
    results = []
    
    for chat_id in subscribers:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": "🔔 <b>ТЕСТОВОЕ УВЕДОМЛЕНИЕ ДЛЯ ВСЕХ</b>\n\nБот работает! ✅",
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            response = requests.post(url, json=data, timeout=10)
            results.append(f"{chat_id}: {response.status_code}")
        except Exception as e:
            results.append(f"{chat_id}: Ошибка - {e}")
    
    return "<br>".join(results)

@app.route('/subscribers')
def list_subscribers():
    """JSON список подписчиков"""
    subscribers = load_subscribers()
    return {
        "total_subscribers": len(subscribers),
        "subscribers": subscribers
    }

@app.route('/add_subscriber/<chat_id>')
def add_sub_manual(chat_id):
    """Добавить подписчика вручную"""
    if add_subscriber(chat_id, "manual"):
        return f"✅ Подписчик {chat_id} добавлен. <a href='/debug'>Вернуться к отладке</a>"
    return f"❌ Ошибка добавления {chat_id}"

# ========== TELEGRAM WEBHOOK ==========

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработчик команд из Telegram"""
    try:
        data = request.get_json()
        
        if 'message' in data:
            chat_id = str(data['message']['chat']['id'])
            text = data['message'].get('text', '')
            username = data['message']['chat'].get('username', '')
            
            logging.info(f"📨 Получено сообщение от {chat_id} ({username}): {text}")
            
            if text == '/start':
                if add_subscriber(chat_id, username):
                    send_telegram_sync(chat_id, 
                        "✅ Вы подписались на уведомления о хоккейных матчах!\n\n"
                        "Я буду присылать уведомления когда появятся новые матчи в продаже на hcdinamo.by"
                    )
                else:
                    send_telegram_sync(chat_id, "ℹ️ Вы уже подписаны на уведомления")
                    
            elif text == '/stop':
                if remove_subscriber(chat_id):
                    send_telegram_sync(chat_id, "❌ Вы отписались от уведомлений")
                else:
                    send_telegram_sync(chat_id, "ℹ️ Вы не подписаны на уведомления")
                    
            elif text == '/status':
                subscribers = load_subscribers()
                if chat_id in subscribers:
                    send_telegram_sync(chat_id, "✅ Вы подписаны на уведомления")
                else:
                    send_telegram_sync(chat_id, "❌ Вы не подписаны на уведомления")
                    
            elif text == '/debug':
                subscribers = load_subscribers()
                status = "✅ подписан" if chat_id in subscribers else "❌ не подписан"
                send_telegram_sync(chat_id, 
                    f"🔍 Информация:\n"
                    f"ID: {chat_id}\n"
                    f"Статус: {status}\n"
                    f"Всего подписчиков: {len(subscribers)}"
                )
        
        return 'OK'
    except Exception as e:
        logging.error(f"❌ Ошибка в webhook: {e}")
        return 'ERROR'

def send_telegram_sync(chat_id, text):
    """Синхронная отправка сообщения в Telegram"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        response = requests.post(url, json=data, timeout=10)
        if response.status_code == 200:
            logging.info(f"✅ Ответ отправлен {chat_id}")
        else:
            logging.error(f"❌ Ошибка отправки ответа: {response.text}")
    except Exception as e:
        logging.error(f"❌ Ошибка отправки ответа: {e}")

# ========== ОСНОВНЫЕ ФУНКЦИИ ==========

def init_db():
    conn = sqlite3.connect('subscribers.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS subscribers (chat_id TEXT PRIMARY KEY, username TEXT)''')
    conn.commit()
    conn.close()

def load_subscribers():
    try:
        conn = sqlite3.connect('subscribers.db')
        c = conn.cursor()
        c.execute("SELECT chat_id FROM subscribers")
        subscribers = [row[0] for row in c.fetchall()]
        conn.close()
        return subscribers
    except:
        return []

def add_subscriber(chat_id, username=""):
    try:
        conn = sqlite3.connect('subscribers.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO subscribers (chat_id, username) VALUES (?, ?)", 
                 (chat_id, username))
        conn.commit()
        conn.close()
        logging.info(f"✅ Добавлен подписчик: {chat_id} ({username})")
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка добавления подписчика: {e}")
        return False

def remove_subscriber(chat_id):
    """Удаление подписчика"""
    try:
        conn = sqlite3.connect('subscribers.db')
        c = conn.cursor()
        c.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        logging.info(f"✅ Удален подписчик: {chat_id}")
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка удаления подписчика: {e}")
        return False

async def send_telegram(text: str):
    subscribers = load_subscribers()
    for chat_id in subscribers:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            data = {
                "chat_id": chat_id, 
                "text": text, 
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            response = requests.post(url, json=data, timeout=10)
            if response.status_code == 200:
                logging.info(f"✅ Уведомление отправлено {chat_id}")
            else:
                logging.error(f"❌ Ошибка отправки {chat_id}: {response.text}")
        except Exception as e:
            logging.error(f"❌ Ошибка отправки сообщения {chat_id}: {e}")

async def fetch_matches():
    try:
        logging.info("🌍 Проверяем новые матчи...")
        response = requests.get(URL, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        matches = []
        for item in soup.select("a.match-item"):
            title = item.select_one("div.match-title")
            date = item.select_one("div.match-day")
            time = item.select_one("div.match-times")
            if title and date and time:
                href = item.get("href", URL)
                if href.startswith("/"):
                    href = "https://hcdinamo.by" + href
                matches.append({
                    "title": title.text.strip(),
                    "date": f"{date.text.strip()} {time.text.strip()}",
                    "url": href
                })
        
        logging.info(f"🎯 Найдено матчей: {len(matches)}")
        return matches
        
    except Exception as e:
        logging.error(f"❌ Ошибка парсинга: {e}")
        return []

async def monitor():
    logging.info("🚀 Запуск мониторинга")
    init_db()
    
    if ADMIN_ID not in load_subscribers():
        add_subscriber(ADMIN_ID, "admin")
        logging.info(f"✅ Автоматически подписан админ: {ADMIN_ID}")
    
    subscribers = load_subscribers()
    logging.info(f"👥 Текущие подписчики: {subscribers}")
    
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            old_matches = json.load(f)
    except:
        old_matches = []
    
    logging.info(f"📂 Загружено предыдущих матчей: {len(old_matches)}")
    
    start_ping_service()
    
    while True:
        try:
            new_matches = await fetch_matches()
            if new_matches:
                old_titles = {m["title"] for m in old_matches}
                new_titles = {m["title"] for m in new_matches}
                
                added = new_titles - old_titles
                removed = old_titles - new_titles
                
                if added or removed:
                    logging.info(f"✨ Изменения: +{len(added)}, -{len(removed)}")
                    
                    # Уведомления о новых матчах
                    for match in new_matches:
                        if match["title"] in added:
                            msg = create_beautiful_message(match)
                            await send_telegram(msg)
                            await asyncio.sleep(1)
                    
                    # Уведомления об удаленных матчах
                    for match in old_matches:
                        if match["title"] in removed:
                            msg = create_removed_message(match)
                            await send_telegram(msg)
                            await asyncio.sleep(1)
                    
                    try:
                        with open(STATE_FILE, "w", encoding="utf-8") as f:
                            json.dump(new_matches, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        logging.error(f"❌ Ошибка сохранения: {e}")
                    
                    old_matches = new_matches
                else:
                    logging.info("✅ Изменений нет")
            
            await asyncio.sleep(CHECK_INTERVAL)
        except Exception as e:
            logging.error(f"Ошибка в цикле: {e}")
            await asyncio.sleep(60)

def run_web_server():
    logging.info("🌐 Запуск веб-сервера на порту 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False)

def main():
    web_thread = Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    time.sleep(3)
    logging.info("🌐 Веб-сервер запущен на порту 5000")
    
    asyncio.run(monitor())

if __name__ == "__main__":
    main()
