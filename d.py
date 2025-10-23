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

# === Конфигурация ===
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
URL = "https://hcdinamo.by/tickets/"
APP_URL = "https://hockey-monitor.onrender.com/version"  # URL для самопинга (минимальный endpoint)

# === Логгирование ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# === Flask ===
app = Flask(__name__)

@app.route('/')
def index():
    return jsonify({"status": "ok", "service": "hockey-monitor"})

@app.route('/version')
def version():
    return jsonify({"version": "2.3.3 - FIXED_DATE_PARSING_AND_KEEP_AWAKE"})

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
        # Извлекаем элементы
        day_elem = item.select_one(".match-day")
        month_elem = item.select_one(".match-month")
        time_elem = item.select_one(".match-times")
        title_elem = item.select_one(".match-title")
        ticket = item.select_one(".btn.tickets-w_t")
        ticket_url = ticket.get("data-w_t") if ticket else None

        # Извлекаем текст, если элементы найдены
        day = day_elem.get_text(strip=True) if day_elem else "?"
        month_raw = month_elem.get_text(strip=True).lower() if month_elem else "?"
        time_ = time_elem.get_text(strip=True) if time_elem else "?"
        title = title_elem.get_text(strip=True) if title_elem else "?"

        # Логируем сырые данные и сам HTML-элемент для отладки
        logging.info(f"Raw date data: day={day}, month_raw={month_raw}")
        if month_elem:
            logging.info(f"Raw HTML for month: {month_elem}")

        # Разделяем месяц и день недели
        month, weekday = "?", "?"
        if month_raw != "?":
            # Проверяем формат "ноя, пт" или просто "ноя"
            match = re.match(r'^([а-я]{3,4})(?:,\s*([а-я]{2}))?$', month_raw)
            if match:
                month = match.group(1)  # Например, "ноя"
                weekday = match.group(2) if match.group(2) else "?"  # Например, "пт" или "?"
            else:
                month = month_raw  # Если нет запятой, считаем, что это только месяц

        # Преобразуем в полные названия
        full_month = MONTHS.get(month, month)  # Если месяц не в словаре, оставляем как есть
        full_weekday = WEEKDAYS.get(weekday, weekday) if weekday != "?" else ""

        # Формируем строку даты
        date_formatted = f"{day} {full_month}" if day != "?" and month != "?" else "Дата неизвестна"
        if full_weekday:
            date_formatted += f", {full_weekday}"

        msg = (
            f"📅 {date_formatted}\n"
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

# === Функция для поддержания сервера awake ===
async def keep_awake():
    await asyncio.sleep(10)  # Задержка на старт
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(APP_URL) as resp:
                    logging.info(f"Keep-awake ping: status {resp.status}")
        except Exception as e:
            logging.error(f"Keep-awake error: {e}")
        await asyncio.sleep(840)  # 14 минут = 840 секунд

# === Запуск aiogram и Flask параллельно ===
async def run_aiogram():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🌐 Webhook удалён, включен polling режим.")
    asyncio.create_task(monitor_matches())
    asyncio.create_task(keep_awake())  # Запускаем самопинг
    await dp.start_polling(bot)

def run_flask():
    app.run(host="0.0.0.0", port=10000)

async def main():
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_flask)  # 🚀 Flask в отдельном потоке
    await run_aiogram()

if __name__ == '__main__':
    asyncio.run(main())
