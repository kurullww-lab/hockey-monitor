import os
import asyncio
import logging
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from bs4 import BeautifulSoup
from aiohttp import web

# === Конфигурация ===
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "https://hockey-monitor.onrender.com")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
URL = "https://hcdinamo.by/tickets/"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

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
last_matches = set()


# === Парсинг матчей ===
async def fetch_matches():
    async with aiohttp.ClientSession() as session:
        async with session.get(URL) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, 'html.parser')
    match_items = soup.select("a.match-item")
    logging.info(f"🎯 Найдено матчей: {len(match_items)}")

    matches = set()
    for item in match_items:
        day = item.select_one(".match-day").get_text(strip=True)
        month = item.select_one(".match-month").get_text(strip=True)
        time_ = item.select_one(".match-times").get_text(strip=True)
        title = item.select_one(".match-title").get_text(strip=True)
        ticket = item.select_one(".btn.tickets-w_t")
        ticket_url = ticket.get("data-w_t") if ticket else None

        match_text = f"{day} {month} {time_} | {title}"
        matches.add((match_text, ticket_url))
    return matches


# === Проверка изменений ===
async def monitor_matches():
    global last_matches
    await asyncio.sleep(5)
    while True:
        try:
            current = await fetch_matches()
            added = current - last_matches
            removed = last_matches - current

            if added or removed:
                logging.info(f"🔔 Изменения: +{len(added)} / -{len(removed)}")
                await notify_changes(added, removed)
                last_matches = current
            else:
                logging.info("✅ Изменений нет")
        except Exception as e:
            logging.error(f"Ошибка при мониторинге: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


# === Рассылка уведомлений ===
async def notify_changes(added, removed):
    if not subscribers:
        logging.info("❕ Нет подписчиков для уведомления")
        return

    for chat_id in subscribers:
        # Новые матчи
        for match, ticket_url in added:
            text = f"🆕 Новый матч добавлен!\n{match}"
            if ticket_url:
                text += f"\n🎟 <a href='{ticket_url}'>Купить билет</a>"
            await bot.send_message(chat_id, text)

        # Удалённые (начавшиеся)
        for match, _ in removed:
            text = f"⏱ Матч начался (удалён с сайта):\n{match}"
            await bot.send_message(chat_id, text)


# === Команды ===
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    subscribers.add(message.chat.id)
    await message.answer("Вы подписаны на уведомления о матчах Динамо Минск! 🏒")
    matches = await fetch_matches()
    if matches:
        for match, ticket in matches:
            msg = f"📅 {match}"
            if ticket:
                msg += f"\n🎟 <a href='{ticket}'>Купить билет</a>"
            await bot.send_message(message.chat.id, msg)
    else:
        await message.answer("Пока нет доступных матчей.")


@dp.message(Command("stop"))
async def stop_cmd(message: types.Message):
    subscribers.discard(message.chat.id)
    await message.answer("Вы отписались от уведомлений.")


# === Flask → aiohttp webhook сервер ===
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    asyncio.create_task(monitor_matches())
    logging.info(f"🌍 Webhook установлен: {WEBHOOK_URL}")


async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()


def main():
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    web.run_app(app, host="0.0.0.0", port=10000)


if __name__ == "__main__":
    main()
