import os
import asyncio
import logging
import threading
import requests
from flask import Flask, request, jsonify
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.types import Update
from aiogram.filters import CommandStart, Command
from aiogram.client.default import DefaultBotProperties
from bs4 import BeautifulSoup
import re
import datetime

# ---------------------- CONFIG ----------------------
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
URL = "https://hcdinamo.by/tickets/"  # Исправленный URL
APP_URL = "https://hockey-monitor.onrender.com/version"  # Для самопинга

# ---------------------- LOGGING ----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------------------- INIT ----------------------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
app = Flask(__name__)

matches_cache = set()
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

# ---------------------- PARSING ----------------------
def fetch_matches():
    try:
        response = requests.get(URL, timeout=10)
        if response.status_code != 200:
            logging.warning(f"⚠️ Ошибка загрузки ({response.status_code}) для URL: {URL}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
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
                match = re.match(r'^([а-я]{3,4})(?:,\s*([а-я]{2}))?$', month_raw)
                if match:
                    month = match.group(1)
                    weekday = match.group(2) if match.group(2) else "?"
                else:
                    month = month_raw

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
            matches.append(msg)
        return matches
    except Exception as e:
        logging.error(f"Ошибка при загрузке матчей: {e}")
        return []

# ---------------------- MONITORING ----------------------
async def monitor_matches():
    global matches_cache
    await asyncio.sleep(5)
    logging.info("🏁 Мониторинг матчей запущен!")

    while True:
        try:
            current_matches = set(fetch_matches())
            added = current_matches - matches_cache
            removed = matches_cache - current_matches

            if added or removed:
                msg = "⚡ Обновления матчей:\n"
                if added:
                    msg += "\n➕ Добавлено:\n" + "\n".join(added)
                if removed:
                    msg += "\n➖ Удалено:\n" + "\n".join(removed)

                for user_id in load_subscribers():
                    try:
                        await bot.send_message(user_id, msg)
                    except Exception as e:
                        logging.warning(f"Ошибка отправки {user_id}: {e}")
            else:
                logging.info("✅ Изменений нет")

            matches_cache = current_matches
        except Exception as e:
            logging.error(f"Ошибка в мониторинге: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

# ---------------------- KEEP AWAKE ----------------------
async def keep_awake():
    current_interval = 840  # 14 минут
    min_interval = 300  # 5 минут при ошибках
    await asyncio.sleep(10)
    while True:
        try:
            response = requests.get(APP_URL, timeout=5)
            if response.status_code == 200:
                logging.info(f"Keep-awake ping: status {response.status_code}")
                current_interval = 840
            else:
                logging.warning(f"Keep-awake неудача: статус {response.status_code}")
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
        matches = fetch_matches()
        msg = f"✅ Вы подписаны на уведомления!\nНайдено матчей: {len(matches)}"
        if matches:
            for match in matches:
                await bot.send_message(message.from_user.id, match)
        else:
            msg += "\nПока нет доступных матчей."
        await message.answer(msg)
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
    return jsonify({"version": "2.3.5 - FIXED_404_AND_ENHANCED"})

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
