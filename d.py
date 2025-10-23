import os
import time
import logging
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from bs4 import BeautifulSoup
from flask import Flask, jsonify

# === Конфигурация ===
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")  # токен из Environment Render
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # твой ID, если нужно логировать
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))  # интервал проверки в секундах

URL = "https://hcdinamo.by/tickets/"
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"https://hockey-monitor.onrender.com{WEBHOOK_PATH}"

# === Настройки логгирования ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# === Flask для Render health-check ===
app = Flask(__name__)

@app.route('/')
def index():
    return jsonify({"status": "ok", "service": "hockey-monitor"})

@app.route('/version')
def version():
    return jsonify({"version": "2.3.1 - SEPARATE_MESSAGES_FIX"})

# === Telegram bot ===
session = AiohttpSession()
bot = Bot(
    token=BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)  # ✅ исправлено под aiogram >= 3.7
)
dp = Dispatcher()

# === Память подписчиков и матчей ===
subscribers = set()
last_matches = []


# === Функция парсинга сайта ===
async def fetch_matches():
    async with aiohttp.ClientSession() as session:
        async with session.get(URL) as response:
            html = await response.text()

    soup = BeautifulSoup(html, 'html.parser')
    match_items = soup.select("a.match-item")
    logging.info(f"🎯 Найдено элементов a.match-item: {len(match_items)}")

    matches = []
    for i, item in enumerate(match_items, start=1):
        day = item.select_one(".match-day").get_text(strip=True)
        month = item.select_one(".match-month").get_text(strip=True)
        time_ = item.select_one(".match-times").get_text(strip=True)
        title = item.select_one(".match-title").get_text(strip=True)
        ticket_div = item.select_one(".btn.tickets-w_t")
        ticket_url = ticket_div.get("data-w_t") if ticket_div else None

        match_text = (
            f"📅 {day} {month}\n"
            f"🏒 {title}\n"
            f"🕒 {time_}\n"
        )
        if ticket_url:
            match_text += f"🎟 <a href='{ticket_url}'>Купить билет</a>"

        matches.append(match_text)
        logging.info(f"🔍 Матч {i}: {day} {month} {time_} | {title}")

    return matches


# === Проверка обновлений ===
async def monitor_matches():
    global last_matches
    await asyncio.sleep(5)  # подождать запуск Flask
    while True:
        try:
            logging.info("🔄 Проверка...")
            matches = await fetch_matches()

            if matches != last_matches:
                logging.info(f"⚡ Обнаружены изменения в матчах ({len(matches)} найдено)")
                last_matches = matches
                await notify_all(matches)
            else:
                logging.info("✅ Изменений нет")
        except Exception as e:
            logging.error(f"Ошибка при мониторинге: {e}")

        logging.info(f"⏰ Следующая проверка через {CHECK_INTERVAL // 60} мин.")
        await asyncio.sleep(CHECK_INTERVAL)


# === Уведомление подписчиков ===
async def notify_all(matches):
    if not subscribers:
        logging.info("❕ Нет подписчиков для уведомления")
        return

    success, failed = 0, 0
    for chat_id in subscribers:
        try:
            for match in matches:
                await bot.send_message(chat_id, match)
            success += 1
        except Exception as e:
            failed += 1
            logging.error(f"Ошибка отправки пользователю {chat_id}: {e}")

    logging.info(f"📊 Итог отправки: ✅ {success} / ❌ {failed}")


# === Команда /start ===
@dp.message(CommandStart())
async def start(message: types.Message):
    chat_id = message.chat.id
    subscribers.add(chat_id)
    logging.info(f"📝 Новый подписчик: {chat_id}")

    await message.answer(
        "Вы подписаны на уведомления о матчах Динамо Минск!\n\n"
        "🏒 Мониторинг запущен! Вы будете получать уведомления о новых матчах."
    )

    matches = await fetch_matches()
    if matches:
        for match in matches:
            await bot.send_message(chat_id, match)
    else:
        await message.answer("Пока нет доступных матчей.")


# === Запуск ===
async def main():
    # Удаляем вебхук перед запуском polling
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🌐 Webhook удалён, включен polling режим.")
    asyncio.create_task(monitor_matches())
    await dp.start_polling(bot)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    app.run(host="0.0.0.0", port=10000)
