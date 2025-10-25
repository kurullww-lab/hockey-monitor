import os
import asyncio
import logging
import threading
from flask import Flask, request
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.types import Update
from aiogram.client.default import DefaultBotProperties
from bs4 import BeautifulSoup

# ---------------------- CONFIG ----------------------
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # опционально
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))  # интервал проверки
URL = "https://hcdinamo.by/matchi/"  # страница с матчами

# ---------------------- LOGGING ----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------------------- INIT BOT ----------------------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

app = Flask(__name__)
matches_cache = set()
subscribers_file = "subscribers.txt"


# ---------------------- UTILS ----------------------
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
    """Парсинг матчей с сайта"""
    response = requests.get(URL)
    if response.status_code != 200:
        logging.warning(f"⚠️ Ошибка загрузки ({response.status_code})")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    match_titles = [div.get_text(strip=True) for div in soup.select("div.match-title")]
    logging.info(f"🎯 Найдено матчей: {len(match_titles)}")
    return match_titles


# ---------------------- MATCH MONITOR ----------------------
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
                    msg += f"\n➕ Добавлено:\n" + "\n".join(added)
                if removed:
                    msg += f"\n➖ Удалено:\n" + "\n".join(removed)

                logging.info(f"⚡ Изменения: добавлено {len(added)}, удалено {len(removed)}")

                for user_id in load_subscribers():
                    try:
                        await bot.send_message(user_id, msg)
                    except Exception as e:
                        logging.warning(f"Не удалось отправить {user_id}: {e}")

            else:
                logging.info("✅ Изменений нет")

            matches_cache = current_matches
        except Exception as e:
            logging.error(f"Ошибка в мониторинге: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


# ---------------------- HANDLERS ----------------------
@dp.message()
async def handle_message(message: types.Message):
    if message.text == "/start":
        save_subscriber(message.from_user.id)
        matches = fetch_matches()
        msg = f"✅ Вы подписаны на обновления!\nНайдено матчей: {len(matches)}"
        await message.answer(msg)
        logging.info(f"📝 Новый подписчик: {message.from_user.id}")

    elif message.text == "/stop":
        subs = load_subscribers()
        subs.discard(str(message.from_user.id))
        with open(subscribers_file, "w") as f:
            f.write("\n".join(subs))
        await message.answer("❌ Вы отписались от уведомлений.")
        logging.info(f"🚫 Пользователь {message.from_user.id} отписался.")


# ---------------------- WEBHOOK ----------------------
@app.post("/webhook")
async def webhook():
    try:
        data = request.json  # dict
        update = Update(**data)  # превращаем dict в Update
        await dp.feed_update(bot, update)
        return "OK"
    except Exception as e:
        logging.error(f"Ошибка webhook: {e}")
        return "Error", 500


@app.get("/")
def index():
    return "✅ Hockey Monitor Bot is running"


# ---------------------- MAIN ----------------------
async def main():
    logging.info("🚀 Starting application...")

    # устанавливаем webhook
    webhook_url = "https://hockey-monitor.onrender.com/webhook"
    await bot.set_webhook(webhook_url)
    logging.info(f"🌍 Webhook установлен: {webhook_url}")

    # запускаем мониторинг в фоне
    asyncio.create_task(monitor_matches())

    # Flask запускаем в отдельном потоке
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()

    # aiogram webhook mode
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("⛔ Bot stopped")
