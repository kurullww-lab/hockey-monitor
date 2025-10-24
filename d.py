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
    import aiohttp
    from bs4 import BeautifulSoup
    import logging

    ajax_url = "https://hcdinamo.by/local/ajax/tickets_list.php"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru,en;q=0.9",
        "Referer": "https://hcdinamo.by/tickets/",
        "Connection": "keep-alive",
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(ajax_url, headers=headers) as resp:
            html = await resp.text()
            logging.info(f"📄 Статус загрузки {resp.status}, длина HTML: {len(html)} символов")

    soup = BeautifulSoup(html, "html.parser")
    match_items = soup.select("a.match-item")
    logging.info(f"🎯 Найдено элементов a.match-item: {len(match_items)}")

    matches = set()
    for item in match_items:
        try:
            day = item.select_one(".match-day").get_text(strip=True)
            month = item.select_one(".match-month").get_text(strip=True)
            time_ = item.select_one(".match-times").get_text(strip=True)
            title = item.select_one(".match-title").get_text(strip=True)
            ticket_btn = item.select_one(".btn.tickets-w_t")
            ticket_url = ticket_btn["data-w_t"] if ticket_btn else None

            match_text = f"{day} {month}, {time_} — {title}"
            matches.add((match_text, ticket_url))
        except Exception as e:
            logging.warning(f"Ошибка парсинга матча: {e}")

    return matches


# === Проверка изменений ===
async def monitor_matches():
    global last_matches
    await asyncio.sleep(5)
    logging.info("🏁 Мониторинг матчей запущен!")
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
    await message.answer("✅ Вы подписаны на уведомления о матчах Динамо Минск! 🏒")

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
    await message.answer("⛔ Вы отписались от уведомлений.")


# === Webhook сервер ===
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    asyncio.create_task(monitor_matches())
    logging.info(f"🌍 Webhook установлен: {WEBHOOK_URL}")


async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()


async def handle_root(request):
    """Проверочный маршрут для Render и Telegram"""
    return web.Response(text="✅ Hockey Monitor Bot is running")


def main():
    app = web.Application()
    app.router.add_get("/", handle_root)  # <-- вот это добавлено
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    web.run_app(app, host="0.0.0.0", port=10000)


if __name__ == "__main__":
    main()
