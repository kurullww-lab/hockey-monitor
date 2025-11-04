import os
import asyncio
import logging
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from bs4 import BeautifulSoup
from flask import Flask, jsonify
import re
import json
import time
from datetime import datetime, timezone, timedelta

# === Конфигурация ===
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
URLS = [
    "https://hcdinamo.by/tickets/",
    "http://hcdinamo.by/tickets/",  # Попробуем HTTP
    "https://www.hcdinamo.by/tickets/",  # Альтернативный URL
]
APP_URL = "https://hockey-monitor.onrender.com/"

# === Настройка часового пояса ===
MOSCOW_TZ = timezone(timedelta(hours=3))

# === Логгирование ===
logging.Formatter.converter = lambda *args: datetime.now(MOSCOW_TZ).timetuple()
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# === Flask ===
app = Flask(__name__)

@app.route('/')
def index():
    return jsonify({"status": "ok", "service": "hockey-monitor"})

@app.route('/version')
def version():
    return jsonify({"version": "2.8.0 - MULTI_URL_FALLBACK"})

@app.route('/subscribers')
def get_subscribers():
    try:
        subs = load_subscribers()
        return jsonify({"subscribers": list(subs)})
    except Exception as e:
        logging.error(f"Ошибка получения подписчиков: {e}")
        return jsonify({"error": str(e)}), 500

# === Telegram bot ===
session = AiohttpSession()
bot = Bot(
    token=BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# === Память ===
subscribers_file = "subscribers.txt"
last_matches = []
last_message_time = {}

# Словари для месяцев и дней недели (остаются без изменений)
MONTHS = {
    "янв": "января", "фев": "февраля", "мар": "марта", "апр": "апреля",
    "май": "мая", "июн": "июня", "июл": "июля", "авг": "августа",
    "сен": "сентября", "окт": "октября", "ноя": "ноября", "дек": "декабря"
}

WEEKDAYS = {
    "пн": "Понедельник", "вт": "Вторник", "ср": "Среда", "чт": "Четверг",
    "пт": "Пятница", "сб": "Суббота", "вс": "Воскресенье"
}

# === Управление подписчиками ===
def load_subscribers():
    if not os.path.exists(subscribers_file):
        return set()
    try:
        with open(subscribers_file, "r") as f:
            return set(f.read().splitlines())
    except Exception as e:
        logging.error(f"Ошибка загрузки подписчиков: {e}")
        return set()

def save_subscriber(user_id):
    subs = load_subscribers()
    subs.add(str(user_id))
    try:
        with open(subscribers_file, "w") as f:
            f.write("\n".join(subs))
        logging.info(f"Сохранён подписчик: {user_id}")
    except Exception as e:
        logging.error(f"Ошибка сохранения подписчика {user_id}: {e}")

def get_moscow_time():
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d %H:%M:%S")

# === Парсинг матчей с множественными URL ===
async def fetch_matches():
    headers_list = [
        {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
        },
        {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        },
        {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
        }
    ]
    
    connector = aiohttp.TCPConnector(verify_ssl=False)  # Отключаем проверку SSL для тестирования
    
    for url_index, url in enumerate(URLS):
        for header_index, headers in enumerate(headers_list):
            try:
                logging.info(f"🔄 Попытка загрузки: {url} с headers #{header_index + 1}")
                
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                    async with session.get(url, headers=headers) as resp:
                        if resp.status == 200:
                            html = await resp.text()
                            logging.info(f"✅ Успешно загружено с {url}, размер: {len(html)} байт")
                            
                            soup = BeautifulSoup(html, 'html.parser')
                            match_items = soup.select("a.match-item")
                            logging.info(f"🎯 Найдено матчей: {len(match_items)}")

                            matches = []
                            for item in match_items:
                                day_elem = item.select_one(".match-day")
                                month_elem = item.select_one(".match-month")
                                time_elem = item.select_one(".match-times")
                                title_elem = item.select_one(".match-title")
                                ticket = item.select_one(".btn.tickets-w_t")
                                ticket_url = ticket.get("data-w_t") if ticket else None
                                away_match_elem = item.select_one(".match-mark")
                                
                                is_away_match = away_match_elem is not None
                                match_type = "🟡 Выездной" if is_away_match else "🔵 Домашний"

                                day = day_elem.get_text(strip=True) if day_elem else "?"
                                month_raw = month_elem.get_text(strip=True).lower() if month_elem else "?"
                                time_ = time_elem.get_text(strip=True) if time_elem else "?"
                                title = title_elem.get_text(strip=True) if title_elem else "?"

                                month, weekday = "?", "?"
                                if month_raw != "?":
                                    match = re.match(r'^([а-я]{3,4})(?:,\s*([а-я]{2}))?$', month_raw, re.IGNORECASE)
                                    if match:
                                        month = match.group(1)
                                        weekday = match.group(2) if match.group(2) else "?"
                                    else:
                                        month = month_raw

                                full_month = MONTHS.get(month, month)
                                full_weekday = WEEKDAYS.get(weekday, weekday) if weekday != "?" else ""

                                date_formatted = f"{day} {full_month}" if day != "?" and month != "?" else "Дата неизвестна"
                                if full_weekday:
                                    date_formatted += f", {full_weekday}"

                                match_id = f"{date_formatted}|{title}|{time_}"

                                match_data = {
                                    "id": match_id,
                                    "date": date_formatted,
                                    "title": title,
                                    "time": time_,
                                    "ticket_url": ticket_url,
                                    "has_ticket": ticket_url is not None,
                                    "is_away_match": is_away_match,
                                    "match_type": match_type
                                }
                                matches.append(match_data)
                            
                            return matches
                        else:
                            logging.warning(f"⚠️ Ошибка {resp.status} для {url} с headers #{header_index + 1}")
                            
            except aiohttp.ClientError as e:
                logging.warning(f"⚠️ Сетевая ошибка для {url}: {e}")
            except Exception as e:
                logging.warning(f"⚠️ Ошибка при загрузке {url}: {e}")
            
            await asyncio.sleep(2)  # Пауза между попытками
    
    logging.error("❌ Все URL и заголовки не сработали")
    return []

# === Остальные функции остаются без изменений ===
def format_match_message(match, include_ticket=True):
    msg = (
        f"{match['match_type']} матч\n"
        f"📅 {match['date']}\n"
        f"🏒 {match['title']}\n"
        f"🕒 {match['time']}\n"
    )
    if include_ticket and match['ticket_url']:
        msg += f"🎟 <a href='{match['ticket_url']}'>Купить билет</a>"
    elif not include_ticket:
        msg += f"❌ Матч начался или отменён"
    return msg

async def monitor_matches():
    global last_matches
    await asyncio.sleep(10)
    logging.info("🏁 Мониторинг матчей запущен!")
    while True:
        try:
            current_matches = await fetch_matches()
            
            if not current_matches:
                logging.warning("⚠️ Не удалось загрузить матчи, пропускаем проверку")
                await asyncio.sleep(CHECK_INTERVAL)
                continue
            
            if last_matches:
                current_dict = {match["id"]: match for match in current_matches}
                last_dict = {match["id"]: match for match in last_matches}
                
                current_ids = set(current_dict.keys())
                last_ids = set(last_dict.keys())
                
                added_ids = current_ids - last_ids
                removed_ids = last_ids - current_ids
                
                if added_ids:
                    for match_id in added_ids:
                        match = current_dict[match_id]
                        if match['has_ticket']:
                            notification_msg = f"🎉 ПОЯВИЛСЯ НОВЫЙ {match['match_type'].upper()} МАТЧ С БИЛЕТАМИ!\n\n{format_match_message(match)}"
                        else:
                            notification_msg = f"🎉 ПОЯВИЛСЯ НОВЫЙ {match['match_type'].upper()} МАТЧ!\n\n{format_match_message(match, include_ticket=False)}\n\nБилеты пока не в продаже"
                        await notify_all([notification_msg])
                
                if removed_ids:
                    for match_id in removed_ids:
                        match = last_dict[match_id]
                        notification_msg = f"⏰ {match['match_type'].upper()} МАТЧ НАЧАЛСЯ!\n\n{format_match_message(match, include_ticket=False)}\n\nУдачи нашей команде! 🏒"
                        await notify_all([notification_msg])
                
                # Проверка билетов для домашних матчей
                ticket_updates = []
                for match_id in current_ids & last_ids:
                    current_match = current_dict[match_id]
                    last_match = last_dict[match_id]
                    if not last_match['has_ticket'] and current_match['has_ticket'] and not current_match['is_away_match']:
                        ticket_updates.append(current_match)
                
                if ticket_updates:
                    for match in ticket_updates:
                        notification_msg = f"🎫 ПОЯВИЛИСЬ БИЛЕТЫ НА ДОМАШНИЙ МАТЧ!\n\n{format_match_message(match)}\n\nУспейте купить! 🏒"
                        await notify_all([notification_msg])
                
                if added_ids or removed_ids or ticket_updates:
                    last_matches = current_matches
                    logging.info(f"🔔 Изменения: +{len(added_ids)} новых, -{len(removed_ids)} удалённых, 🎫{len(ticket_updates)} с билетами")
                else:
                    logging.info("✅ Изменений нет")
            else:
                last_matches = current_matches
                logging.info("📝 Первоначальная загрузка матчей завершена")
                
        except Exception as e:
            logging.error(f"Ошибка при мониторинге: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

async def notify_all(messages, chat_ids=None):
    subscribers = load_subscribers() if chat_ids is None else set(chat_ids)
    if not subscribers:
        return
    for chat_id in subscribers:
        for msg in messages:
            try:
                await bot.send_message(chat_id, msg)
            except Exception as e:
                logging.error(f"Ошибка при отправке пользователю {chat_id}: {e}")

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    user_id = message.chat.id
    current_time = time.time()
    if user_id in last_message_time and current_time - last_message_time[user_id] < 60:
        return
    last_message_time[user_id] = current_time

    save_subscriber(user_id)
    logging.info(f"📝 Новый подписчик: {user_id}")
    await message.answer("Вы подписаны на уведомления о матчах Динамо Минск! 🏒")
    
    matches = await fetch_matches()
    if matches:
        for match in matches:
            await message.answer(format_match_message(match))
    else:
        await message.answer("❌ Не удалось загрузить матчи. Попробуйте позже.")

@dp.message(Command("stop"))
async def stop_cmd(message: types.Message):
    user_id = message.chat.id
    subscribers = load_subscribers()
    subscribers.discard(str(user_id))
    try:
        with open(subscribers_file, "w") as f:
            f.write("\n".join(subscribers))
        await message.answer("Вы отписались от уведомлений.")
        logging.info(f"❌ Пользователь {user_id} отписался.")
    except Exception as e:
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")

@dp.message(Command("status"))
async def status_cmd(message: types.Message):
    current_time = get_moscow_time()
    matches_with_tickets = sum(1 for match in last_matches if match['has_ticket']) if last_matches else 0
    home_matches = sum(1 for match in last_matches if not match['is_away_match']) if last_matches else 0
    away_matches = sum(1 for match in last_matches if match['is_away_match']) if last_matches else 0
    
    status_msg = (
        f"🛠 Статус бота:\n"
        f"👥 Подписчиков: {len(load_subscribers())}\n"
        f"🏒 Всего матчей: {len(last_matches)}\n"
        f"🔵 Домашних: {home_matches}\n"
        f"🟡 Выездных: {away_matches}\n"
        f"🎫 С билетами: {matches_with_tickets}\n"
        f"⏰ Текущее время: {current_time}\n"
        f"🔄 Интервал проверки: {CHECK_INTERVAL} сек"
    )
    await message.answer(status_msg)

async def keep_awake():
    await asyncio.sleep(60)
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(APP_URL, timeout=10) as resp:
                    if resp.status == 200:
                        logging.info("Keep-awake ping: OK")
        except Exception:
            pass
        await asyncio.sleep(300)  # Каждые 5 минут

async def run_aiogram():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🌐 Webhook удалён, включен polling режим.")
    asyncio.create_task(monitor_matches())
    asyncio.create_task(keep_awake())
    await dp.start_polling(bot)

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

async def main():
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_flask)
    await run_aiogram()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("⛔ Bot stopped")
