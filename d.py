import os
import asyncio
import logging
import aiohttp
from aiohttp import web
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import Message
import json
from pathlib import Path

# ------------------- НАСТРОЙКА ЛОГГИРОВАНИЯ -------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ------------------- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ -------------------
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # твой ID (для отладки)
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
WEBHOOK_HOST = "https://hockey-monitor.onrender.com"
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# ------------------- ОБЪЕКТЫ -------------------
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# ------------------- ФАЙЛ С ПОДПИСЧИКАМИ -------------------
SUBSCRIBERS_FILE = Path("subscribers.json")

def load_subscribers():
    if SUBSCRIBERS_FILE.exists():
        try:
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logging.warning("⚠️ Ошибка чтения subscribers.json, создаётся новый файл.")
    return []

def save_subscribers(subscribers):
    try:
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(subscribers, f)
    except Exception as e:
        logging.error(f"Ошибка при сохранении subscribers.json: {e}")

# ------------------- ОСНОВНОЙ URL С МАТЧАМИ -------------------
URL = "https://hcdinamo.by/tickets/"

# ------------------- ХРАНЕНИЕ МАТЧЕЙ -------------------
previous_matches = set()

# ------------------- ПАРСИНГ МАТЧЕЙ -------------------
async def fetch_matches():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(URL, headers={"User-Agent": "Mozilla/5.0"}) as response:
                html = await response.text()
                logging.info(f"📄 Статус: {response.status}, длина HTML: {len(html)} символов")

                if response.status != 200:
                    logging.warning("⚠️ Ошибка загрузки страницы, статус не 200")
                    return []

                soup = BeautifulSoup(html, "html.parser")
                match_items = soup.select("a.match-item")

                logging.info(f"🎯 Найдено элементов a.match-item: {len(match_items)}")

                matches = []
                for item in match_items:
                    date_day = item.select_one(".match-day")
                    date_month = item.select_one(".match-month")
                    date_time = item.select_one(".match-times")
                    title = item.select_one(".match-title")
                    link_tag = item.get("href")

                    if not (date_day and date_month and date_time and title):
                        continue

                    match_str = f"{date_day.text.strip()} {date_month.text.strip()} {date_time.text.strip()} — {title.text.strip()} | {link_tag}"
                    matches.append(match_str)

                unique = list(set(matches))
                logging.info(f"🎯 Уникальных матчей: {len(unique)}")
                return unique

    except Exception as e:
        logging.error(f"Ошибка при парсинге: {e}")
        return []

# ------------------- ОТПРАВКА СООБЩЕНИЙ -------------------
async def notify_all(subscribers, new_matches, removed_matches):
    for chat_id in subscribers:
        try:
            if new_matches:
                for m in new_matches:
                    parts = m.split("—")
                    if len(parts) == 2:
                        text = (
                            f"📅 <b>{parts[0].split('|')[0].strip()}</b>\n"
                            f"🏒 {parts[1].split('|')[0].strip()}\n"
                            f"🎟 <a href='{m.split('|')[1].strip()}'>Купить билет</a>"
                        )
                        await bot.send_message(chat_id, text)
            if removed_matches:
                for m in removed_matches:
                    text = f"❌ Матч удалён: {m}"
                    await bot.send_message(chat_id, text)
        except Exception as e:
            logging.error(f"Ошибка при отправке пользователю {chat_id}: {e}")

# ------------------- МОНИТОРИНГ -------------------
async def monitor_matches():
    global previous_matches
    await asyncio.sleep(5)
    logging.info("🏁 Мониторинг матчей запущен!")

    while True:
        matches = await fetch_matches()
        if matches:
            new = set(matches) - previous_matches
            removed = previous_matches - set(matches)
            if new or removed:
                logging.info(f"⚡ Обновления: добавлено {len(new)}, удалено {len(removed)}")
                subscribers = load_subscribers()
                await notify_all(subscribers, new, removed)
            else:
                logging.info("✅ Изменений нет")
            previous_matches = set(matches)
        await asyncio.sleep(CHECK_INTERVAL)

# ------------------- КОМАНДЫ -------------------
@dp.message(F.text == "/start")
async def start_handler(message: Message):
    subscribers = load_subscribers()
    if message.chat.id not in subscribers:
        subscribers.append(message.chat.id)
        save_subscribers(subscribers)
        logging.info(f"📝 Новый подписчик: {message.chat.id}")
        await message.answer("Вы подписаны на уведомления о матчах Динамо Минск!")

        matches = await fetch_matches()
        if matches:
            for m in matches:
                parts = m.split("—")
                if len(parts) == 2:
                    text = (
                        f"📅 <b>{parts[0].split('|')[0].strip()}</b>\n"
                        f"🏒 {parts[1].split('|')[0].strip()}\n"
                        f"🎟 <a href='{m.split('|')[1].strip()}'>Купить билет</a>"
                    )
                    await message.answer(text)
        else:
            await message.answer("Матчи не найдены на сайте.")
    else:
        await message.answer("Вы уже подписаны на уведомления о матчах.")

@dp.message(F.text == "/stop")
async def stop_handler(message: Message):
    subscribers = load_subscribers()
    if message.chat.id in subscribers:
        subscribers.remove(message.chat.id)
        save_subscribers(subscribers)
        await message.answer("Вы отписаны от уведомлений о матчах.")
        logging.info(f"🚫 Отписался: {message.chat.id}")
    else:
        await message.answer("Вы не были подписаны.")

# ------------------- FLASK-СЕРВЕР -------------------
async def handle_webhook(request):
    try:
        data = await request.json()
        await dp.feed_webhook_update(bot, data)
        return web.Response(status=200)
    except Exception as e:
        logging.error(f"Ошибка в webhook: {e}")
        return web.Response(status=500)

async def on_startup(app):
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)
    asyncio.create_task(monitor_matches())
    logging.info(f"🌍 Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app):
    await bot.session.close()

def main():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, handle_webhook)
    app.router.add_get("/", lambda _: web.Response(text="Hockey Monitor is running!"))
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    web.run_app(app, port=10000)

if __name__ == "__main__":
    main()
