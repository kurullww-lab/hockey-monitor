import os
import asyncio
import logging
import threading
import aiohttp
from flask import Flask, request, jsonify
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.types import Update
from aiogram.filters import CommandStart, Command
from aiogram.client.default import DefaultBotProperties
from bs4 import BeautifulSoup
import re
import datetime
import json

# ---------------------- CONFIG ----------------------
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
URL = "https://hcdinamo.by/tickets/"
APP_URL = "https://hockey-monitor.onrender.com/version"
MATCHES_CACHE_FILE = "matches_cache.json"

# ---------------------- LOGGING ----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------------------- INIT ----------------------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
app = Flask(__name__)

matches_cache = []
subscribers_file = "subscribers.txt"
main_loop = None

# Словарь для месяцев
MONTHS = {
    "янв": "января",
    "фев": "февраля",
    "мар": "марта",
    "апр": "апреля",
    "май": "мая",
    "июн": "июня",
    "июл": "июля",
    "авг": "августа",
    "сен": "сентября",
    "окт": "октября",
    "ноя": "ноября",
    "дек": "декабря"
}

# Словарь для дней недели
WEEKDAYS = {
    "пн": "Понедельник",
    "вт": "Вторник",
    "ср": "Среда",
    "чт": "Четверг",
    "пт": "Пятница",
    "сб": "Суббота",
    "вс": "Воскресенье"
}

# ---------------------- CACHE MANAGEMENT ----------------------
def load_matches_cache():
    if not os.path.exists(MATCHES_CACHE_FILE):
        return []
    try:
        with open(MATCHES_CACHE_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Ошибка загрузки кэша матчей: {e}")
        return []

def save_matches_cache(matches):
    try:
        with open(MATCHES_CACHE_FILE, "w") as f:
            json.dump(matches, f)
    except Exception as e:
        logging.error(f"Ошибка сохранения кэша матчей: {e}")

# ---------------------- SUBSCRIBERS ----------------------
def load_subscribers():
    if not os.path.exists(subscribers_file):
        return set()
    with open(subscribers_file, "r") as f:
        return set(f.read().splitlines())

def save_subscriber(user_id):
    subs = load_subscribers()
    subs.add(str(user_id))
    with open(subscribers_file, "w") as f:
        f.write("\n".join(subs))
    logging.info(f"Сохранён подписчик: {user_id}")

# ---------------------- PARSING ----------------------
async def fetch_matches():
    retries = 3
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(URL, timeout=15) as resp:
                    if resp.status != 200:
                        logging.warning(f"⚠️ Ошибка загрузки ({resp.status}) для URL: {URL}")
                        continue
                    html = await resp.text()

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

                day = day_elem.get_text(strip=True) if day_elem else "?"
                month_raw = month_elem.get_text(strip=True).lower() if month_elem else "?"
                time_ = time_elem.get_text(strip=True) if time_elem else "?"
                title = title_elem.get_text(strip=True) if title_elem else "?"

                logging.info(f"Raw date data: day={day}, month_raw={month_raw}")
                if month_elem:
                    logging.info(f"Raw HTML for month: {month_elem}")

                month, weekday = "?", "?"
                if month_raw != "?":
                    match = re.match(r'^([а-я]{3,4})(?:,\s*([а-я]{2}))?$', month_raw, re.IGNORECASE)
                    if match:
                        month = match.group(1).lower()
                        weekday = match.group(2).lower() if match.group(2) else "?"
                    else:
                        month = month_raw.lower()

                full_month = MONTHS.get(month, month)
                full_weekday = WEEKDAYS.get(weekday, weekday) if weekday != "?" else ""

                date_formatted = f"{day} {full_month} 2025" if day != "?" and month != "?" else "Дата неизвестна"
                if full_weekday:
                    date_formatted += f", {full_weekday}"

                venue_emoji = "🏟" if "Динамо-Минск" in title.split(" — ")[0] else "✈️"

                msg = (
                    f"📅 {date_formatted}\n"
                    f"{venue_emoji} {title}\n"
                    f"🕒 {time_}\n"
                )
                if ticket_url:
                    msg += f"🎟 <a href='{ticket_url}'>Купить билет</a>"

                match_key = f"{date_formatted}|{title}|{time_}"
                matches.append((match_key, msg))
            
            matches.sort(key=lambda x: x[0])
            return [msg for _, msg in matches]
        except aiohttp.ClientError as e:
            logging.error(f"Ошибка сети на попытке {attempt + 1}/{retries}: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(5)
        except Exception as e:
            logging.error(f"Неожиданная ошибка при парсинге: {e}")
            return []
    logging.error("Все попытки исчерпаны, возвращаем пустой список")
    return []

# ---------------------- MONITORING ----------------------
async def monitor_matches():
    global matches_cache
    matches_cache = load_matches_cache()
    await asyncio.sleep(5)
    logging.info("🏁 Мониторинг матчей запущен!")

    while True:
        try:
            current_matches = await fetch_matches()
            current_keys = {f"{msg}" for msg in current_matches}
            cached_keys = {f"{msg}" for msg in matches_cache}

            added = [msg for msg in current_matches if f"{msg}" not in cached_keys]
            removed = [msg for msg in matches_cache if f"{msg}" not in current_keys]

            if added or removed:
                msg = "⚡ Обновления матчей:\n"
                if added:
                    msg += "\n➕ Добавлено:\n" + "\n".join(added)
                if removed:
                    msg += "\n➖ Удалено:\n" + "\n".join(removed)

                for user_id in load_subscribers():
                    try:
                        await bot.send_message(user_id, msg)
                        logging.info(f"Уведомление отправлено пользователю {user_id}")
                    except Exception as e:
                        logging.warning(f"Ошибка отправки {user_id}: {e}")
                logging.info(f"🔔 Отправлены уведомления о {len(added)} новых и {len(removed)} удалённых матчах")
                matches_cache = current_matches
                save_matches_cache(matches_cache)
            else:
                logging.info("✅ Изменений нет")

        except Exception as e:
            logging.error(f"Ошибка в мониторинге: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

# ---------------------- KEEP AWAKE ----------------------
async def keep_awake():
    current_interval = 840  # 14 минут
    min_interval = 300  # 5 минут при ошибках
    await asyncio.sleep(60)  # Увеличенная задержка
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(APP_URL, timeout=5) as resp:
                    response_text = await resp.text()
                    if resp.status == 200:
                        logging.info(f"Keep-awake ping: status {resp.status}, response: {response_text[:50]}...")
                        current_interval = 840
                    else:
                        logging.warning(f"Keep-awake неудача: статус {resp.status}, response: {response_text[:50]}...")
                        current_interval = max(current_interval - 60, min_interval)
        except Exception as e:
            logging.error(f"Keep-awake error: {e}")
            current_interval = max(current_interval - 60, min_interval)
        await asyncio.sleep(current_interval)

# ---------------------- HANDLERS ----------------------
@dp.message()
async def handle_message(message: types.Message):
    if message.text == "/start":
        save_subscriber(message.from_user.id)
        matches = await fetch_matches()
        msg = f"✅ Вы подписаны на уведомления!\nНайдено матчей: {len(matches)}"
        await message.answer(msg)
        if matches:
            for match in matches:
                await bot.send_message(message.from_user.id, match)
                logging.info(f"Отправлен матч пользователю {message.from_user.id}: {match[:50]}...")
        else:
            await message.answer("Пока нет доступных матчей.")
        logging.info(f"📝 Новый подписчик: {message.from_user.id}")

    elif message.text == "/stop":
        subs = load_subscribers()
        subs.discard(str(message.from_user.id))
        with open(subscribers_file, "w") as f:
            f.write("\n".join(subs))
        await message.answer("❌ Вы отписались от уведомлений.")
        logging.info(f"🚫 Пользователь {message.from_user.id} отписался.")

    elif message.text == "/status":
        last_check = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_msg = (
            f"🛠 Статус бота:\n"
            f"👥 Подписчиков: {len(load_subscribers())}\n"
            f"🏒 Матчей в кэше: {len(matches_cache)}\n"
            f"⏰ Последняя проверка: {last_check}\n"
            f"🔄 Интервал проверки: {CHECK_INTERVAL} сек"
        )
        await message.answer(status_msg)

# ---------------------- FLASK ROUTES ----------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update_data = request.get_json()
        update = Update(**update_data)
        asyncio.run_coroutine_threadsafe(dp.feed_update(bot, update), main_loop)
        return "OK"
    except Exception as e:
        logging.error(f"Ошибка webhook: {e}")
        return "Error", 500

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "service": "hockey-monitor"})

@app.route("/version", methods=["GET"])
def version():
    return jsonify({"version": "2.3.7 - FIXED_PING_AND_NOTIFICATIONS"})

# ---------------------- MAIN ----------------------
async def main():
    global main_loop
    main_loop = asyncio.get_running_loop()

    logging.info("🚀 Starting application...")
    await bot.delete_webhook()

    webhook_url = "https://hockey-monitor.onrender.com/webhook"
    await bot.set_webhook(webhook_url)
    logging.info(f"🌍 Webhook установлен: {webhook_url}")

    asyncio.create_task(monitor_matches())
    asyncio.create_task(keep_awake())

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("⛔ Bot stopped")
        save_matches_cache(matches_cache)
