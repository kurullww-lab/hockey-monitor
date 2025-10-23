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

# === Конфигурация ===
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
URL = "https://hcdinamo.by/tickets/"

# === Логгирование ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# === Flask ===
app = Flask(__name__)

@app.route('/')
def index():
    return jsonify({"status": "ok", "service": "hockey-monitor"})

@app.route('/version')
def version():
    return jsonify({"version": "2.3.2 - FIXED_PARALLEL_RUN"})

# === Telegram bot ===
session = AiohttpSession()
bot = Bot(
    token=BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# === Память ===
subscribers = set()
last_matches = []


# === Парсинг матчей ===
async def fetch_matches():
    async with aiohttp.ClientSession() as session:
        async with session.get(URL) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, 'html.parser')
    match_items = soup.select("a.match-item")
    logging.info(f"🎯 Найдено матчей: {len(match_items)}")

    matches = []
    for item in match_items:
        day = item.select_one(".match-day").get_text(strip=True)
        month = item.select_one(".match-month").get_text(strip=True)
        time_ = item.select_one(".match-times").get_text(strip=True)
        title = item.select_one(".match-title").get_text(strip=True)
        ticket = item.select_one(".btn.tickets-w_t")
        ticket_url = ticket.get("data-w_t") if ticket else None

        msg = (
            f"📅 {day} {month}\n"
            f"🏒 {title}\n"
            f"🕒 {time_}\n"
        )
        if ticket_url:
            msg += f"🎟 <a href='{ticket_url}'>Купить билет</a>"
        matches.append(msg)
    return matches


# === Проверка обновлений ===
async def monitor_matches():
    global last_matches
    await asyncio.sleep(5)
    while True:
        try:
            matches = await fetch_matches()
            if matches != last_matches:
                last_matches = matches
                await notify_all(matches)
            else:
                logging.info("✅ Изменений нет")
        except Exception as e:
            logging.error(f"Ошибка при мониторинге: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


# === Отправка уведомлений ===
async def notify_all(matches):
    if not subscribers:
        logging.info("❕ Нет подписчиков для уведомления")
        return
    for chat_id in subscribers:
        for match in matches:
            try:
                await bot.send_message(chat_id, match)
            except Exception as e:
                logging.error(f"Ошибка при отправке пользователю {chat_id}: {e}")


# === Команда /start ===
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    subscribers.add(message.chat.id)
    logging.info(f"📝 Новый подписчик: {message.chat.id}")
    await message.answer("Вы подписаны на уведомления о матчах Динамо Минск! 🏒")
    matches = await fetch_matches()
    if matches:
        for match in matches:
            await bot.send_message(message.chat.id, match)
    else:
        await message.answer("Пока нет доступных матчей.")


# === Команда /stop ===
@dp.message(Command("stop"))
async def stop_cmd(message: types.Message):
    subscribers.discard(message.chat.id)
    await message.answer("Вы отписались от уведомлений.")
    logging.info(f"❌ Пользователь {message.chat.id} отписался.")


# === Запуск aiogram и Flask параллельно ===
async def run_aiogram():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🌐 Webhook удалён, включен polling режим.")
    asyncio.create_task(monitor_matches())
    await dp.start_polling(bot)


def run_flask():
    app.run(host="0.0.0.0", port=10000)


async def main():
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_flask)  # 🚀 Flask в отдельном потоке
    await run_aiogram()


if __name__ == '__main__':
    asyncio.run(main())
