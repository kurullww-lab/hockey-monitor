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
RENDER_URL = "https://hockey-monitor.onrender.com"

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt='%Y-%m-%d %H:%M:%S'
)

app = Flask(__name__)

# ========== НАСТРОЙКА WEBHOOK ==========

def setup_webhook():
    """Настройка webhook для Telegram"""
    try:
        webhook_url = f"{RENDER_URL}/webhook"
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            logging.info(f"✅ Webhook настроен: {webhook_url}")
            return True
        else:
            logging.error(f"❌ Ошибка настройки webhook: {response.text}")
            return False
    except Exception as e:
        logging.error(f"❌ Ошибка настройки webhook: {e}")
        return False

# ========== ДИАГНОСТИКА ==========

async def check_bot_status():
    """Проверка статуса бота и подписчиков"""
    # Проверяем токен бота
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            bot_info = response.json()['result']
            logging.info(f"✅ Бот активен: {bot_info['username']} ({bot_info['first_name']})")
        else:
            logging.error(f"❌ Неверный токен бота: {response.text}")
            return False
    except Exception as e:
        logging.error(f"❌ Ошибка проверки бота: {e}")
        return False
    
    # Проверяем подписчиков
    subscribers = load_subscribers()
    logging.info(f"👥 Всего подписчиков: {len(subscribers)}")
    for sub in subscribers:
        logging.info(f"   - {sub} {'(ADMIN)' if sub == ADMIN_ID else ''}")
    
    return True

# ========== КРАСИВЫЕ УВЕДОМЛЕНИЯ ==========

def format_beautiful_date(date_string):
    """Красивое форматирование даты матча с правильным определением месяца"""
    try:
        logging.info(f"🔧 Форматируем дату: '{date_string}'")
        
        months_ru = [
            'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
            'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
        ]
        
        months_ru_short = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 
                          'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
        
        # Пытаемся найти месяц в строке
        date_lower = date_string.lower()
        
        for i, month in enumerate(months_ru):
            if month in date_lower:
                # Нашли полное название месяца
                parts = date_string.split()
                day = parts[0] if parts else "?"
                time = parts[-1] if len(parts) > 1 else "?"
                current_year = datetime.now().year
                
                # Если месяц уже прошел в этом году, значит это следующий год
                if i + 1 < datetime.now().month:
                    current_year += 1
                    
                return f"🗓 {day} {month} {current_year} ⏰ {time}"
        
        # Пробуем короткие названия месяцев
        for i, month_short in enumerate(months_ru_short):
            if month_short in date_lower:
                parts = date_string.split()
                day = parts[0] if parts else "?"
                time = parts[-1] if len(parts) > 1 else "?"
                current_year = datetime.now().year
                full_month = months_ru[i]
                
                if i + 1 < datetime.now().month:
                    current_year += 1
                    
                return f"🗓 {day} {full_month} {current_year} ⏰ {time}"
        
        # Если месяц не указан, определяем логически
        parts = date_string.split()
        if len(parts) >= 2:
            day_str = parts[0]
            time = parts[1]
            
            try:
                match_day = int(day_str)
                now = datetime.now()
                current_day = now.day
                current_month = now.month
                current_year = now.year
                
                if match_day < current_day:
                    # Матч в следующем месяце
                    match_month = current_month + 1
                    if match_month > 12:
                        match_month = 1
                        current_year += 1
                else:
                    # Матч в текущем месяце
                    match_month = current_month
                
                if 1 <= match_month <= 12:
                    month_name = months_ru[match_month - 1]
                    return f"🗓 {day_str} {month_name} {current_year} ⏰ {time}"
                    
            except ValueError:
                # Не удалось преобразовать день в число
                pass
        
        # Если ничего не помогло, возвращаем оригинальную строку
        return f"📅 {date_string}"
        
    except Exception as e:
        logging.error(f"❌ Ошибка форматирования даты '{date_string}': {e}")
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
    def ping_loop():
        while True:
            try:
                response = requests.get(f"{RENDER_URL}/health", timeout=10)
                logging.info(f"🏓 Авто-пинг: {response.status_code}")
            except Exception as e:
                logging.error(f"❌ Ошибка авто-пинга: {e}")
            time.sleep(PING_INTERVAL)
    
    ping_thread = Thread(target=ping_loop, daemon=True)
    ping_thread.start()
    logging.info("🔔 Служба авто-пинга запущена")

# ========== WEB ЭНДПОИНТЫ ==========

@app.route('/')
def home():
    return "🏒 Hockey Monitor Bot is running!"

@app.route('/health')
def health():
    return {"status": "running", "timestamp": datetime.now().isoformat()}

@app.route('/debug')
def debug():
    subscribers = load_subscribers()
    
    html = f"""
    <html>
        <head><title>Debug Info</title><meta charset="utf-8"></head>
        <body>
            <h1>🏒 Debug Information</h1>
            <h2>👥 Подписчики ({len(subscribers)}):</h2>
            <ul>
    """
    
    for sub in subscribers:
        html += f"<li><b>{sub}</b> {'(ADMIN)' if sub == ADMIN_ID else ''}</li>"
    
    html += f"""
            </ul>
            <p><b>ADMIN_ID:</b> {ADMIN_ID}</p>
            <hr>
            <p><a href="/test_send_all">📤 Тестовая отправка всем</a></p>
            <p><a href="/setup_webhook">🔄 Настроить Webhook</a></p>
            <p><a href="/check_bot">🔍 Проверить бота</a></p>
        </body>
    </html>
    """
    
    return html

@app.route('/test_send_all')
def test_send_all():
    """Тестовая отправка всем подписчикам с детальной информацией"""
    subscribers = load_subscribers()
    results = []
    
    for chat_id in subscribers:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": "🔔 <b>ТЕСТОВОЕ УВЕДОМЛЕНИЕ</b>\n\nЭто тестовое сообщение для проверки работы бота! ✅",
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            response = requests.post(url, json=data, timeout=10)
            if response.status_code == 200:
                results.append(f"✅ {chat_id}: Успешно")
            else:
                results.append(f"❌ {chat_id}: Ошибка {response.status_code} - {response.text}")
        except Exception as e:
            results.append(f"❌ {chat_id}: Исключение - {e}")
    
    return "<br>".join(results)

@app.route('/setup_webhook')
def setup_webhook_route():
    """Настройка webhook через веб-интерфейс"""
    if setup_webhook():
        return "✅ Webhook настроен успешно! <a href='/debug'>Назад</a>"
    else:
        return "❌ Ошибка настройки webhook! <a href='/debug'>Назад</a>"

@app.route('/check_bot')
def check_bot_route():
    """Проверка бота через веб-интерфейс"""
    import threading
    
    def check():
        asyncio.run(check_bot_status())
    
    thread = Thread(target=check)
    thread.start()
    
    return "🔍 Проверка бота запущена, смотрите логи. <a href='/debug'>Назад</a>"

@app.route('/add_subscriber/<chat_id>')
def add_sub_manual(chat_id):
    """Добавить подписчика вручную"""
    if add_subscriber(chat_id, "manual"):
        # Отправляем тестовое сообщение новому подписчику
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": "✅ Вы были добавлены в список подписчиков Hockey Monitor!",
            "parse_mode": "HTML"
        }
        try:
            requests.post(url, json=data, timeout=10)
        except:
            pass
            
        return f"✅ Подписчик {chat_id} добавлен и отправлено уведомление. <a href='/debug'>Назад</a>"
    return f"❌ Ошибка добавления {chat_id}"

# ========== TELEGRAM WEBHOOK ==========

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработчик команд из Telegram"""
    try:
        data = request.get_json()
        logging.info(f"📨 Получен webhook: {json.dumps(data, ensure_ascii=False)}")
        
        if 'message' in data:
            chat_id = str(data['message']['chat']['id'])
            text = data['message'].get('text', '')
            username = data['message']['chat'].get('username', '')
            first_name = data['message']['chat'].get('first_name', '')
            
            logging.info(f"💬 Сообщение от {chat_id} ({username}): {text}")
            
            if text == '/start':
                if add_subscriber(chat_id, username or first_name):
                    send_telegram_sync(chat_id, 
                        f"✅ Привет, {first_name}!\n\n"
                        "Вы подписались на уведомления о хоккейных матчах!\n\n"
                        "Я буду присылать уведомления когда появятся новые матчи в продаже на hcdinamo.by"
                    )
                    logging.info(f"👤 Новый подписчик: {chat_id} ({username})")
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
                    f"🔍 Ваша информация:\n"
                    f"ID: {chat_id}\n"
                    f"Статус: {status}\n"
                    f"Всего подписчиков: {len(subscribers)}"
                )
            else:
                send_telegram_sync(chat_id, 
                    "🤖 Команды бота:\n"
                    "/start - Подписаться на уведомления\n"
                    "/stop - Отписаться от уведомлений\n" 
                    "/status - Статус подписки\n"
                    "/debug - Информация о подписке"
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
            logging.error(f"❌ Ошибка отправки ответа {chat_id}: {response.text}")
    except Exception as e:
        logging.error(f"❌ Ошибка отправки ответа {chat_id}: {e}")

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
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки подписчиков: {e}")
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
    logging.info(f"📤 Отправка уведомления {len(subscribers)} подписчикам: {subscribers}")
    
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
                
                # Логируем сырые данные для отладки
                logging.info(f"📋 Сырые данные: '{date.text.strip()}' '{time.text.strip()}'")
                
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
    
    # Настраиваем webhook
    setup_webhook()
    
    # Проверяем статус бота
    await check_bot_status()
    
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
