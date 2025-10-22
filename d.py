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

# ========== УЛУЧШЕННЫЙ ПАРСИНГ ДАТ ==========

def parse_match_date(date_string):
    """Улучшенный парсинг даты матча с учетом текущего сезона"""
    try:
        logging.info(f"🔧 Парсим дату: '{date_string}'")
        
        # Словари месяцев
        months_ru = {
            'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
            'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
        }
        
        months_ru_short = {
            'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4, 'мая': 5, 'июн': 6,
            'июл': 7, 'авг': 8, 'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12
        }
        
        # Приводим к нижнему регистру
        date_lower = date_string.lower().strip()
        
        # Разбираем части даты
        parts = date_string.split()
        if len(parts) < 2:
            logging.warning(f"⚠️ Недостаточно частей в дате: {date_string}")
            return datetime.now()
        
        # Извлекаем день и время
        day_str = parts[0].strip()
        time_str = parts[-1].strip()
        
        # Определяем год хоккейного сезона (сезон обычно с августа по апрель)
        current_date = datetime.now()
        current_year = current_date.year
        current_month = current_date.month
        
        # Хоккейный сезон: если сейчас с августа по декабрь - это текущий год
        # если с января по июль - это следующий год для матчей после августа
        season_year = current_year
        
        # Пытаемся найти месяц в строке
        month_found = None
        for month_name, month_num in months_ru.items():
            if month_name in date_lower:
                month_found = month_num
                break
                
        if not month_found:
            for month_short, month_num in months_ru_short.items():
                if month_short in date_lower:
                    month_found = month_num
                    break
        
        # Если месяц не нашли, используем текущий месяц как fallback
        if not month_found:
            logging.warning(f"⚠️ Не найден месяц в дате: {date_string}")
            month_found = current_month
        
        # ЛОГИКА ОПРЕДЕЛЕНИЯ ГОДА ДЛЯ ХОККЕЙНОГО СЕЗОНА:
        # Матчи обычно идут с сентября по апрель
        # Если текущий месяц с января по июль, а матч с сентября по декабрь - это следующий год
        # Если текущий месяц с августа по декабрь, а матч с января по июль - это следующий год
        
        if current_month >= 8:  # Август-Декабрь
            if month_found >= 1 and month_found <= 7:  # Январь-Июль
                season_year = current_year + 1
            else:  # Август-Декабрь
                season_year = current_year
        else:  # Январь-Июль
            if month_found >= 8:  # Август-Декабрь
                season_year = current_year
            else:  # Январь-Июль
                season_year = current_year
        
        # Парсим время
        try:
            if ':' in time_str:
                hours, minutes = map(int, time_str.split(':'))
            else:
                # Пытаемся извлечь время из строки регулярным выражением
                time_match = re.search(r'(\d{1,2}):(\d{2})', time_str)
                if time_match:
                    hours, minutes = int(time_match.group(1)), int(time_match.group(2))
                else:
                    hours, minutes = 19, 0  # время по умолчанию
        except:
            hours, minutes = 19, 0
        
        # Парсим день
        try:
            day = int(day_str)
        except:
            # Пытаемся извлечь день регулярным выражением
            day_match = re.search(r'(\d{1,2})', day_str)
            if day_match:
                day = int(day_match.group(1))
            else:
                day = 1
        
        # Создаем объект datetime
        match_date = datetime(season_year, month_found, day, hours, minutes)
        
        # Дополнительная проверка: если дата в прошлом более чем на 30 дней, 
        # значит это следующий год (для случаев когда сезон переходит через год)
        if match_date < current_date and (current_date - match_date).days > 30:
            match_date = match_date.replace(year=season_year + 1)
            logging.info(f"🔄 Корректируем год для прошедшей даты: {match_date}")
        
        logging.info(f"✅ Дата распарсена: {match_date.strftime('%d.%m.%Y %H:%M')}")
        return match_date
        
    except Exception as e:
        logging.error(f"❌ Ошибка парсинга даты '{date_string}': {e}")
        return datetime.now()

def format_beautiful_date(date_string):
    """Красивое форматирование даты матча с правильным определением месяца и года"""
    try:
        # Парсим дату для получения корректного года
        parsed_date = parse_match_date(date_string)
        
        months_ru = [
            'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
            'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
        ]
        
        # Извлекаем время из исходной строки
        time_match = re.search(r'(\d{1,2}:\d{2})', date_string)
        time_str = time_match.group(1) if time_match else "19:00"
        
        day = parsed_date.day
        month_name = months_ru[parsed_date.month - 1]
        year = parsed_date.year
        
        return f"🗓 {day} {month_name} {year} ⏰ {time_str}"
        
    except Exception as e:
        logging.error(f"❌ Ошибка форматирования даты '{date_string}': {e}")
        return f"📅 {date_string}"

# ========== ПРОВЕРКА КОРРЕКТНОСТИ РАСПИСАНИЯ ==========

def validate_schedule(matches):
    """Проверка корректности расписания матчей"""
    logging.info("🔍 Проверка корректности расписания...")
    
    # Группируем матчи по дате
    matches_by_date = {}
    for match in matches:
        date_key = match["parsed_date"].strftime('%Y-%m-%d')
        if date_key not in matches_by_date:
            matches_by_date[date_key] = []
        matches_by_date[date_key].append(match)
    
    # Проверяем матчи в один день
    issues = []
    for date, day_matches in matches_by_date.items():
        if len(day_matches) > 1:
            # Проверяем, все ли матчи в один день домашние/выездные
            home_games = [m for m in day_matches if m['title'].startswith('Динамо-Минск')]
            away_games = [m for m in day_matches if not m['title'].startswith('Динамо-Минск')]
            
            if home_games and away_games:
                issue = f"❌ В один день ({date}) есть и домашний и выездной матч!"
                issues.append(issue)
                logging.error(issue)
    
    if issues:
        logging.warning(f"⚠️ Обнаружены проблемы в расписании: {len(issues)}")
        for issue in issues:
            logging.warning(f"   {issue}")
    
    return len(issues) == 0

# ========== ОСТАЛЬНОЙ КОД БЕЗ ИЗМЕНЕНИЙ ==========

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

async def send_telegram_with_retry(text: str, max_retries=3):
    subscribers = load_subscribers()
    logging.info(f"📤 Отправка уведомления {len(subscribers)} подписчикам")
    
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
                response = requests.post(url, json=data, timeout=10)
                
                if response.status_code == 200:
                    logging.info(f"✅ Уведомление отправлено {chat_id}")
                    break
                else:
                    error_msg = response.json().get('description', 'Unknown error')
                    logging.warning(f"⚠️ Попытка {attempt + 1}/{max_retries} для {chat_id}: {error_msg}")
                    
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)
                    else:
                        logging.error(f"❌ Не удалось отправить {chat_id} после {max_retries} попыток")
                        
            except Exception as e:
                logging.warning(f"⚠️ Попытка {attempt + 1}/{max_retries} для {chat_id}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                else:
                    logging.error(f"❌ Не удалось отправить {chat_id} после {max_retries} попыток: {e}")

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
                
                match_data = {
                    "title": title.text.strip(),
                    "date": f"{date.text.strip()} {time.text.strip()}",
                    "url": href
                }
                
                match_data["parsed_date"] = parse_match_date(match_data["date"])
                matches.append(match_data)
        
        # Сортировка по дате
        matches.sort(key=lambda x: x["parsed_date"])
        
        # Проверка корректности расписания
        validate_schedule(matches)
        
        logging.info(f"🎯 Найдено матчей: {len(matches)}")
        for match in matches:
            logging.info(f"   - {match['parsed_date'].strftime('%d.%m.%Y %H:%M')}: {match['title']}")
        
        return matches
        
    except Exception as e:
        logging.error(f"❌ Ошибка парсинга: {e}")
        return []

async def monitor():
    logging.info("🚀 Запуск мониторинга")
    init_db()
    
    setup_webhook()
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
                    
                    for match in new_matches:
                        if match["title"] in added:
                            msg = create_beautiful_message(match)
                            await send_telegram_with_retry(msg)
                            await asyncio.sleep(1)
                    
                    for match in old_matches:
                        if match["title"] in removed:
                            msg = create_removed_message(match)
                            await send_telegram_with_retry(msg)
                            await asyncio.sleep(1)
                    
                    try:
                        with open(STATE_FILE, "w", encoding="utf-8") as f:
                            save_matches = [{"title": m["title"], "date": m["date"], "url": m["url"]} 
                                          for m in new_matches]
                            json.dump(save_matches, f, ensure_ascii=False, indent=2)
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
