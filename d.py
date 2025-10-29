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
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
URL = "https://hcdinamo.by/matchi/"  # проверь, чтобы был актуальный URL

# ---------------------- LOGGING ----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------------------- INIT ----------------------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
app = Flask(__name__)

matches_cache = set()
subscribers_file = "subscribers.txt"
main_loop = None  # глобальная ссылка на event loop


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
            logging.warning(f"⚠️ Ошибка загрузки ({response.status_code})")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        titles = [div.get_text(strip=True) for div in soup.select("div.match-title")]
        logging.info(f"🎯 Найдено матчей: {len(titles)}")
        return titles
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


# ---------------------- HANDLERS ----------------------
@dp.message()
async def handle_message(message: types.Message):
    if message.text == "/start":
        save_subscriber(message.from_user.id)
        matches = fetch_matches()
        msg = f"✅ Вы подписаны на уведомления!\nНайдено матчей: {len(matches)}"
        await message.answer(msg)
        logging.info(f"📝 Новый подписчик: {message.from_user.id}")

    elif message.text == "/stop":
        subs = load_subscribers()
        subs.discard(str(message.from_user.id))
        with open(subscribers_file, "w") as f:
            f.write("\n".join(subs))
        await message.answer("❌ Вы отписались от уведомлений.")
        logging.info(f"🚫 Пользователь {message.from_user.id} отписался.")


# ---------------------- FLASK ROUTES ----------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update_data = request.get_json()
        update = Update(**update_data)

        # используем глобальный event loop
        asyncio.run_coroutine_threadsafe(dp.feed_update(bot, update), main_loop)

        return "OK"
    except Exception as e:
        logging.error(f"Ошибка webhook: {e}")
        return "Error", 500


@app.route("/", methods=["GET"])
def index():
    return "✅ Hockey Monitor Bot is running"


# ---------------------- MAIN ----------------------
async def main():
    global main_loop
    main_loop = asyncio.get_running_loop()

    logging.info("🚀 Starting application...")
    await bot.delete_webhook()

    webhook_url = "https://hockey-monitor.onrender.com/webhook"
    await bot.set_webhook(webhook_url)
    logging.info(f"🌍 Webhook установлен: {webhook_url}")

    # запускаем мониторинг матчей
    asyncio.create_task(monitor_matches())

    # Flask в отдельном потоке
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("⛔ Bot stopped")
