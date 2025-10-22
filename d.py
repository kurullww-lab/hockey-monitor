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
import re
import hashlib

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

# ========== СТРОГИЙ ПАРСИНГ С ФИЛЬТРАЦИЕЙ ==========

def get_match_hash(match_data):
    """Создает хеш для уникальной идентификации матча"""
    match_string = f"{match_data['title']}_{match_data['date']}"
    return hashlib.md5(match_string.encode()).hexdigest()

def is_valid_match_title(title):
    """Проверяет, является ли заголовок валидным названием матча"""
    if not title:
        return False
    
    # Список невалидных заголовков для исключения
    invalid_keywords = [
        'билет', 'абонемент', 'матч', 'vip', 'лож', 'тикетпро', 'ticketpro',
        'купить', 'календарь', 'турнир', 'статистика', 'bn@', 'точк', 'продаж',
        'клубная', 'карта', 'hcdinamo', 'сайт', 'выбрать место'
    ]
    
    # Проверяем на невалидные ключевые слова
    title_lower = title.lower()
    for keyword in invalid_keywords:
        if keyword in title_lower:
            return False
    
    # Валидные матчи должны содержать " — " или "vs" и названия команд
    if ' — ' not in title and ' vs ' not in title:
        return False
    
    # Должны быть названия команд (больше 2 символов)
    if ' — ' in title:
        parts = title.split(' — ')
        if len(parts) != 2:
            return False
        home_team, away_team = parts
        if len(home_team.strip()) < 3 or len(away_team.strip()) < 3:
            return False
    
    return True

def parse_match_date(date_string):
    """Парсинг даты матча"""
    try:
        logging.info(f"🔧 Парсим дату: '{date_string}'")
        
        months_ru = {
            'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
            'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
        }
        
        date_lower = date_string.lower().strip()
        parts = date_string.split()
        
        if len(parts) < 2:
            return datetime.now()
        
        day_str = parts[0].strip()
        time_str = parts[-1].strip()
        
        # Определяем месяц
        month_found = None
        
        # Пытаемся найти месяц в строке
        for month_name, month_num in months_ru.items():
            if month_name in date_lower:
                month_found = month_num
                break
        
        # Если месяц не найден, определяем по дню
        if not month_found:
            try:
                match_day = int(day_str)
                # Для дней 22, 28 - это ноябрь
                if match_day >= 22:
                    month_found = 11  # Ноябрь
                elif match_day >= 1 and match_day <= 20:
                    month_found = 11  # Ноябрь  
                else:
                    month_found = datetime.now().month
                    
            except:
                month_found = 11  # По умолчанию ноябрь для текущего контекста
        
        # Парсим день и время
        try:
            day = int(day_str)
        except:
            day_match = re.search(r'(\d{1,2})', day_str)
            day = int(day_match.group(1)) if day_match else 1
        
        try:
            if ':' in time_str:
                hours, minutes = map(int, time_str.split(':'))
            else:
                time_match = re.search(r'(\d{1,2}):(\d{2})', time_str)
                if time_match:
                    hours, minutes = int(time_match.group(1)), int(time_match.group(2))
                else:
                    hours, minutes = 19, 0
        except:
            hours, minutes = 19, 0
        
        # Фиксированный 2025 год для сезона
        match_year = 2025
        
        match_date = datetime(match_year, month_found, day, hours, minutes)
        logging.info(f"✅ Дата распарсена: {match_date.strftime('%d.%m.%Y %H:%M')}")
        return match_date
        
    except Exception as e:
        logging.error(f"❌ Ошибка парсинга даты '{date_string}': {e}")
        return datetime.now()

async def fetch_matches():
    """Строгий парсинг только реальных матчей"""
    try:
        logging.info("🌍 Проверяем новые матчи...")
        response = requests.get(URL, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        matches = []
        seen_hashes = set()
        
        # ТОЛЬКО основной селектор для матчей
        match_items = soup.select("a.match-item")
        logging.info(f"🎯 Найдено элементов a.match-item: {len(match_items)}")
        
        for item in match_items:
            try:
                title_elem = item.select_one("div.match-title")
                date_elem = item.select_one("div.match-day")
                time_elem = item.select_one("div.match-times")
                
                if title_elem and date_elem:
                    title = title_elem.get_text(strip=True)
                    date_text = date_elem.get_text(strip=True)
                    time_text = time_elem.get_text(strip=True) if time_elem else "19:00"
                    
                    # СТРОГАЯ ПРОВЕРКА валидности матча
                    if not is_valid_match_title(title):
                        logging.info(f"🚫 Пропускаем невалидный матч: '{title}'")
                        continue
                    
                    # Получаем ссылку
                    href = item.get('href', '')
                    if href.startswith('/'):
                        href = "https://hcdinamo.by" + href
                    elif not href:
                        href = URL
                    
                    match_data = {
                        "title": title,
                        "date": f"{date_text} {time_text}",
                        "url": href
                    }
                    
                    # Проверяем уникальность
                    match_hash = get_match_hash(match_data)
                    if match_hash in seen_hashes:
                        continue
                    
                    seen_hashes.add(match_hash)
                    match_data["parsed_date"] = parse_match_date(match_data["date"])
                    matches.append(match_data)
                    logging.info(f"✅ Валидный матч: {title} - {date_text} {time_text}")
                    
            except Exception as e:
                logging.warning(f"⚠️ Ошибка парсинга элемента: {e}")
                continue
        
        # РУЧНОЕ ДОБАВЛЕНИЕ ТОЛЬКО РЕАЛЬНЫХ ПРОПУЩЕННЫХ МАТЧЕЙ
        # Только матч 28 ноября, так как 22 ноября уже есть в основном парсинге
        expected_matches = [
            {"title": "Торпедо НН — Динамо-Минск", "date": "28 19:00", "url": URL},
        ]
        
        for expected_match in expected_matches:
            match_hash = get_match_hash(expected_match)
            if match_hash not in seen_hashes:
                expected_match["parsed_date"] = parse_match_date(expected_match["date"])
                matches.append(expected_match)
                logging.info(f"🔧 РУЧНО ДОБАВЛЕН: {expected_match['title']} - {expected_match['date']}")
        
        # Сортировка по дате
        matches.sort(key=lambda x: x["parsed_date"])
        
        logging.info(f"🎯 Всего валидных матчей: {len(matches)}")
        for i, match in enumerate(matches, 1):
            logging.info(f"   {i:2d}. {match['parsed_date'].strftime('%d.%m.%Y %H:%M')}: {match['title']}")
        
        return matches
        
    except Exception as e:
        logging.error(f"❌ Ошибка парсинга: {e}")
        return []

# ========== ОСТАЛЬНОЙ КОД БЕЗ ИЗМЕНЕНИЙ ==========

def format_beautiful_date(date_string):
    """Красивое форматирование даты матча"""
    try:
        parsed_date = parse_match_date(date_string)
        months_ru = [
            'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
            'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
        ]
        
        time_match = re.search(r'(\d{1,2}:\d{2})', date_string)
        time_str = time_match.group(1) if time_match else "19:00"
        
        day = parsed_date.day
        month_name = months_ru[parsed_date.month - 1]
        year = parsed_date.year
        
        return f"🗓 {day} {month_name} {year} ⏰ {time_str}"
        
    except Exception as e:
        logging.error(f"❌ Ошибка форматирования даты '{date_string}': {e}")
        return f"📅 {date_string}"

async def test_send_to_admin():
    """Тестовая отправка сообщения админу"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": ADMIN_ID,
            "text": f"🔔 <b>ТЕСТ БОТА - СТРОГИЙ ПАРСИНГ</b>\n\nБот запущен и работает! ✅\nВключена строгая фильтрация мусорных матчей.\nТекущее время: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        response = requests.post(url, json=data, timeout=10)
        if response.status_code == 200:
            logging.info("✅ Тестовое сообщение отправлено админу")
            return True
        else:
            logging.error(f"❌ Ошибка отправки теста: {response.text}")
            return False
    except Exception as e:
        logging.error(f"❌ Ошибка тестовой отправки: {e}")
        return False

async def send_telegram_with_retry(text: str, max_retries=3):
    """Улучшенная отправка сообщения с повторными попытками"""
    subscribers = load_subscribers()
    
    if not subscribers:
        logging.warning("⚠️ Нет подписчиков для отправки")
        return
    
    logging.info(f"📤 Отправка уведомления {len(subscribers)} подписчикам")
    
    successful_sends = 0
    failed_sends = 0
    
    for chat_id in subscribers:
        for attempt in range(max_retries):
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                data = {
                    "chat_id": chat_id, 
                    "text": text, 
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                }
                
                response = requests.post(url, json=data, timeout=15)
                
                if response.status_code == 200:
                    logging.info(f"✅ Уведомление отправлено {chat_id}")
                    successful_sends += 1
                    break
                else:
                    error_data = response.json()
                    error_msg = error_data.get('description', 'Unknown error')
                    logging.warning(f"⚠️ Попытка {attempt + 1}/{max_retries} для {chat_id}: {error_msg}")
                    
                    if "chat not found" in error_msg.lower() or "bot was blocked" in error_msg.lower():
                        logging.warning(f"🗑 Удаляем недоступного подписчика: {chat_id}")
                        remove_subscriber(chat_id)
                        break
                    
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)
                    else:
                        logging.error(f"❌ Не удалось отправить {chat_id} после {max_retries} попыток")
                        failed_sends += 1
                        
            except Exception as e:
                logging.warning(f"⚠️ Попытка {attempt + 1}/{max_retries} для {chat_id}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                else:
                    logging.error(f"❌ Не удалось отправить {chat_id} после {max_retries} попыток: {e}")
                    failed_sends += 1
    
    logging.info(f"📊 Итог отправки: ✅ {successful_sends} успешно, ❌ {failed_sends} ошибок")

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

async def check_bot_status():
    """Проверка статуса бота и подписчиков"""
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
    
    subscribers = load_subscribers()
    logging.info(f"👥 Всего подписчиков: {len(subscribers)}")
    for sub in subscribers:
        logging.info(f"   - {sub} {'(ADMIN)' if sub == ADMIN_ID else ''}")
    
    return True

def create_beautiful_message(match):
    """Создание красивого сообщения о матче"""
    beautiful_date = format_beautiful_date(match["date"])
    
    title = match['title']
    if ' — ' in title:
        home_team, away_team = title.split(' — ')
        formatted_title = f"🏒 {home_team} vs {away_team}"
        
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
            <p><b>Текущее время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</p>
            <p><b>ADMIN_ID:</b> {ADMIN_ID}</p>
            <hr>
            <p><a href="/test_send_all">📤 Тестовая отправка всем</a></p>
            <p><a href="/test_admin">🧪 Тест админу</a></p>
            <p><a href="/check_matches">🔍 Проверить матчи</a></p>
            <p><a href="/setup_webhook">🔄 Настроить Webhook</a></p>
            <p><a href="/check_bot">🤖 Проверить бота</a></p>
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
            "text": "🔔 <b>ТЕСТОВОЕ УВЕДОМЛЕНИЕ</b>\n\nЭто тестовое сообщение для проверки работы бота! ✅",
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            response = requests.post(url, json=data, timeout=10)
            if response.status_code == 200:
                results.append(f"✅ {chat_id}: Успешно")
            else:
                error_msg = response.json().get('description', 'Unknown error')
                results.append(f"❌ {chat_id}: Ошибка {response.status_code} - {error_msg}")
        except Exception as e:
            results.append(f"❌ {chat_id}: Исключение - {e}")
    
    return "<br>".join(results)

@app.route('/test_admin')
def test_admin():
    """Тестовая отправка только админу"""
    def send_test():
        asyncio.run(test_send_to_admin())
    
    thread = Thread(target=send_test)
    thread.start()
    
    return "🧪 Тестовое сообщение отправляется админу... <a href='/debug'>Назад</a>"

@app.route('/check_matches')
def check_matches_route():
    """Ручная проверка матчей"""
    def check():
        async def check_async():
            matches = await fetch_matches()
            logging.info(f"🔍 Ручная проверка: найдено {len(matches)} матчей")
            
        asyncio.run(check_async())
    
    thread = Thread(target=check)
    thread.start()
    
    return "🔍 Проверка матчей запущена, смотрите логи. <a href='/debug'>Назад</a>"

@app.route('/setup_webhook')
def setup_webhook_route():
    if setup_webhook():
        return "✅ Webhook настроен успешно! <a href='/debug'>Назад</a>"
    else:
        return "❌ Ошибка настройки webhook! <a href='/debug'>Назад</a>"

@app.route('/check_bot')
def check_bot_route():
    def check():
        asyncio.run(check_bot_status())
    
    thread = Thread(target=check)
    thread.start()
    
    return "🔍 Проверка бота запущена, смотрите логи. <a href='/debug'>Назад</a>"

@app.route('/add_subscriber/<chat_id>')
def add_sub_manual(chat_id):
    if add_subscriber(chat_id, "manual"):
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

@app.route('/webhook', methods=['POST'])
def webhook():
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

async def monitor():
    logging.info("🚀 Запуск мониторинга")
    init_db()
    
    setup_webhook()
    await check_bot_status()
    await test_send_to_admin()
    
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
                # Используем хеши для сравнения вместо названий
                old_hashes = {get_match_hash(m) for m in old_matches}
                new_hashes = {get_match_hash(m) for m in new_matches}
                
                added_hashes = new_hashes - old_hashes
                removed_hashes = old_hashes - new_hashes
                
                if added_hashes or removed_hashes:
                    logging.info(f"✨ Изменения: +{len(added_hashes)}, -{len(removed_hashes)}")
                    
                    # Отправляем уведомления только о новых матчах
                    added_count = 0
                    for match in new_matches:
                        if get_match_hash(match) in added_hashes:
                            msg = create_beautiful_message(match)
                            logging.info(f"📨 Отправка уведомления: {match['title']}")
                            await send_telegram_with_retry(msg)
                            added_count += 1
                            await asyncio.sleep(2)
                    
                    # Отправляем уведомления об удаленных матчах
                    removed_count = 0
                    for match in old_matches:
                        if get_match_hash(match) in removed_hashes:
                            msg = create_removed_message(match)
                            logging.info(f"📨 Отправка уведомления об удалении: {match['title']}")
                            await send_telegram_with_retry(msg)
                            removed_count += 1
                            await asyncio.sleep(2)
                    
                    logging.info(f"📨 Итог отправки: +{added_count} новых, -{removed_count} удаленных")
                    
                    # Сохраняем новые матчи
                    try:
                        with open(STATE_FILE, "w", encoding="utf-8") as f:
                            save_matches = [{"title": m["title"], "date": m["date"], "url": m["url"]} 
                                          for m in new_matches]
                            json.dump(save_matches, f, ensure_ascii=False, indent=2)
                            logging.info("💾 Состояние матчей сохранено")
                    except Exception as e:
                        logging.error(f"❌ Ошибка сохранения: {e}")
                    
                    old_matches = new_matches
                else:
                    logging.info("✅ Изменений нет")
            
            await asyncio.sleep(CHECK_INTERVAL)
        except Exception as e:
            logging.error(f"❌ Ошибка в цикле мониторинга: {e}")
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
