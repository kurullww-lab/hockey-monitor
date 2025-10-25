import os
import asyncio
import logging
import aiohttp
from aiohttp import web
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command

# === Настройки логирования ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# === Константы ===
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))  # интервал проверки в секундах (по умолчанию 5 мин)
BASE_URL = "https://hcdinamo.by/tickets/"
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"https://hockey-monitor.onrender.com{WEBHOOK_PATH}"

# === Инициализация бота ===
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# === Глобальные данные ===
subscribers = set()
previous_matches = []

# === Функция парсинга матчей ===
async def fetch_matches():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BASE_URL, headers=headers) as response:
                if response.status != 200:
                    logging.error(f"Ошибка загрузки страницы: {response.status}")
                    return []

                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")

                match_list_block = soup.select_one("div.match-list")
                if not match_list_block:
                    logging.warning("⚠️ Блок .match-list не найден на странице!")
                    return []

                matches_raw = match_list_block.select("a.match-item")
                logging.info(f"🔍 Найдено элементов a.match-item в .match-list: {len(matches_raw)}")

                matches = []
                seen = set()  # для исключения дубликатов

                for tag in matches_raw:
                    day = tag.select_one(".match-day")
                    month = tag.select_one(".match-month")
                    time = tag.select_one(".match-times")
                    title = tag.select_one(".match-title")

                    if not (day and month and time and title):
                        continue

                    link = tag.get("href") or tag.get("data-w_t")
                    if not link:
                        continue

                    link = link if link.startswith("http") else f"https://hcdinamo.by{link}"
                    key = (title.text.strip(), link)
                    if key in seen:
                        continue
                    seen.add(key)

                    matches.append({
                        "day": day.text.strip(),
                        "month": month.text.strip(),
                        "time": time.text.strip(),
                        "title": title.text.strip(),
                        "url": link
                    })

                logging.info(f"🎯 Уникальных матчей: {len(matches)}")
                return matches

    except Exception as e:
        logging.error(f"Ошибка парсинга: {e}")
        return []

# === Проверка изменений матчей ===
async def check_for_updates():
    global previous_matches

    matches = await fetch_matches()
    if not matches:
        logging.info("✅ Изменений нет (или сайт недоступен)")
        return

    if matches != previous_matches:
        added = [m for m in matches if m not in previous_matches]
        removed = [m for m in previous_matches if m not in matches]
        previous_matches = matches

        if added or removed:
            logging.info(f"⚡ Обновления: добавлено {len(added)}, удалено {len(removed)}")

            for chat_id in subscribers:
                # Новые матчи
                for m in added:
                    msg = (
                        f"📅 <b>{m['day']} {m['month']}</b> {m['time']}\n"
                        f"🏒 {m['title']}\n"
                        f"🎟 <a href='{m['url']}'>Купить билет</a>"
                    )
                    try:
                        await bot.send_message(chat_id, msg)
                    except Exception as e:
                        logging.error(f"Ошибка отправки сообщения: {e}")

                # Удалённые матчи (например, начались)
                for m in removed:
                    msg = (
                        f"❌ Матч удалён с сайта (возможно, начался)\n"
                        f"📅 <b>{m['day']} {m['month']}</b> {m['time']}\n"
                        f"🏒 {m['title']}"
                    )
                    try:
                        await bot.send_message(chat_id, msg)
                    except Exception as e:
                        logging.error(f"Ошибка уведомления об удалении: {e}")
    else:
        logging.info("✅ Изменений нет")

# === Периодический мониторинг ===
async def scheduler():
    while True:
        await check_for_updates()
        await asyncio.sleep(CHECK_INTERVAL)

# === Обработчики Telegram ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.chat.id
    if user_id not in subscribers:
        subscribers.add(user_id)
        await message.answer("✅ Вы подписаны на уведомления о матчах Динамо Минск!")
        logging.info(f"📝 Новый подписчик: {user_id}")
    else:
        await message.answer("Вы уже подписаны.")

@dp.message(Command("stop"))
async def cmd_stop(message: types.Message):
    user_id = message.chat.id
    if user_id in subscribers:
        subscribers.remove(user_id)
        await message.answer("❌ Вы отписались от уведомлений.")
        logging.info(f"🚫 Подписчик удалён: {user_id}")
    else:
        await message.answer("Вы не были подписаны.")

# === Flask-like сервер для Webhook ===
async def handle_webhook(request):
    try:
        update = await request.json()
        await dp.feed_webhook_update(bot, update)
        return web.Response(text="ok")
    except Exception as e:
        logging.error(f"Ошибка в webhook: {e}")
        return web.Response(status=500)

async def start_bot():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, handle_webhook)
    app.router.add_get("/", lambda request: web.Response(text="Bot is running!"))

    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"🌍 Webhook установлен: {WEBHOOK_URL}")

    asyncio.create_task(scheduler())

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()

    logging.info("🏁 Мониторинг матчей запущен!")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(start_bot())
