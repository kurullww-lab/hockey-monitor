import os
import logging
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from flask import Flask, request
from bs4 import BeautifulSoup
import threading
import time

# === Конфигурация ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # твой Telegram ID
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))  # каждые 5 минут

URL = "https://hcdinamo.by/tickets/"
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"https://hockey-monitor.onrender.com{WEBHOOK_PATH}"

# === Настройка логов ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

app = Flask(__name__)
subscribers = set()
previous_matches = []

# === Парсинг матчей ===
async def fetch_matches():
    async with aiohttp.ClientSession() as session:
        async with session.get(URL) as response:
            html = await response.text()
    soup = BeautifulSoup(html, "html.parser")
    matches = []

    for a in soup.select("a.match-item"):
        try:
            day = a.select_one(".match-day").text.strip()
            month = a.select_one(".match-month").text.strip()
            time_ = a.select_one(".match-times").text.strip()
            title = a.select_one(".match-title").text.strip()
            link = a["href"]
            matches.append({
                "day": day, "month": month, "time": time_,
                "title": title, "link": link
            })
        except Exception as e:
            logging.error(f"Ошибка парсинга матча: {e}")
    logging.info(f"🎯 Найдено матчей: {len(matches)}")
    return matches

# === Проверка изменений ===
async def monitor_changes():
    global previous_matches
    while True:
        try:
            matches = await fetch_matches()
            if matches != previous_matches:
                added = [m for m in matches if m not in previous_matches]
                removed = [m for m in previous_matches if m not in matches]

                if added:
                    for match in added:
                        text = (
                            f"📅 <b>{match['day']} {match['month']}</b> {match['time']}\n"
                            f"🏒 {match['title']}\n"
                            f"<a href='{match['link']}'>🎟 Купить билет</a>"
                        )
                        for uid in subscribers:
                            await bot.send_message(uid, text)
                previous_matches = matches
            else:
                logging.info("✅ Изменений нет")
        except Exception as e:
            logging.error(f"❌ Ошибка мониторинга: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

# === Команда /start ===
@dp.message(Command("start"))
async def start_command(message: types.Message):
    subscribers.add(message.from_user.id)
    await message.answer("Вы подписаны на уведомления о матчах Динамо-Минск! 🏒")

# === Flask Webhook ===
@app.route(WEBHOOK_PATH, methods=["POST"])
async def webhook():
    update = types.Update.model_validate(await request.json)
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.route("/", methods=["GET"])
def home():
    return "✅ Hockey Monitor bot is running."

@app.route("/version", methods=["GET"])
def version():
    return "2.3 - WEBHOOK MODE"

# === Запуск Flask + бота ===
def start_webhook():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def on_startup():
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(WEBHOOK_URL)
        logging.info(f"🌐 Webhook установлен: {WEBHOOK_URL}")
        asyncio.create_task(monitor_changes())

    loop.run_until_complete(on_startup())
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

if __name__ == "__main__":
    start_webhook()
