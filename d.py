import os
import json
import asyncio
import logging
from aiohttp import web, ClientSession
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ===============================
# 🔧 НАСТРОЙКИ
# ===============================
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = "https://hockey-monitor.onrender.com/webhook"
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
SUBSCRIBERS_FILE = "subscribers.json"
MATCHES_FILE = "matches.json"
TARGET_URL = "https://hcdinamo.by/matches/"  # можно поменять при необходимости

# ===============================
# ⚙️ НАСТРОЙКА ЛОГИРОВАНИЯ
# ===============================
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

# ===============================
# 🧠 ИНИЦИАЛИЗАЦИЯ БОТА
# ===============================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# ===============================
# 📁 УТИЛИТЫ
# ===============================
def load_json(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_subscribers():
    return load_json(SUBSCRIBERS_FILE)

def save_subscribers(subs):
    save_json(SUBSCRIBERS_FILE, subs)

def load_matches():
    return load_json(MATCHES_FILE)

def save_matches(matches):
    save_json(MATCHES_FILE, matches)

# ===============================
# 🕸 ПАРСЕР
# ===============================
async def fetch_matches():
    async with ClientSession() as session:
        async with session.get(TARGET_URL, headers={"User-Agent": "Mozilla/5.0"}) as resp:
            html = await resp.text()
            logging.info(f"📄 Статус: {resp.status}, длина HTML: {len(html)} символов")
            if resp.status != 200:
                return []
            soup = BeautifulSoup(html, "html.parser")
            matches = []

            items = soup.select("a.match-item")
            logging.info(f"🎯 Найдено элементов a.match-item: {len(items)}")

            for a in items:
                title_tag = a.select_one(".match-title")
                day = a.select_one(".match-day")
                month = a.select_one(".match-month")
                time = a.select_one(".match-times")
                link = a.get("href")

                if title_tag and day and month and time:
                    title = title_tag.text.strip()
                    date = f"{day.text.strip()} {month.text.strip()} {time.text.strip()}"
                    matches.append({
                        "title": title,
                        "date": date,
                        "link": link
                    })
            # Убираем дубликаты по title+date
            unique = {f"{m['title']}|{m['date']}": m for m in matches}
            logging.info(f"🎯 Уникальных матчей: {len(unique)}")
            return list(unique.values())

# ===============================
# 🔁 МОНИТОРИНГ
# ===============================
async def monitor_matches():
    logging.info("🏁 Мониторинг матчей запущен!")
    while True:
        try:
            current = await fetch_matches()
            saved = load_matches()

            added = [m for m in current if m not in saved]
            removed = [m for m in saved if m not in current]

            if added or removed:
                logging.info(f"⚡ Обновления: добавлено {len(added)}, удалено {len(removed)}")
                save_matches(current)
                await notify_subscribers(added, removed)
            else:
                logging.info("✅ Изменений нет")

        except Exception as e:
            logging.error(f"❌ Ошибка мониторинга: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

# ===============================
# 📣 УВЕДОМЛЕНИЯ
# ===============================
async def notify_subscribers(added, removed):
    subs = load_subscribers()
    if not subs:
        logging.info("❕ Нет подписчиков для уведомления")
        return

    for chat_id in subs:
        if added:
            for match in added:
                msg = (
                    f"📅 <b>{match['date']}</b>\n"
                    f"🏒 {match['title']}\n"
                    f"🎟 <a href='{match['link']}'>Купить билет</a>"
                )
                await bot.send_message(chat_id, msg)

        if removed:
            for match in removed:
                msg = f"⚠️ Матч удалён: {match['title']} ({match['date']})"
                await bot.send_message(chat_id, msg)

# ===============================
# 🤖 ОБРАБОТЧИКИ
# ===============================
@dp.message()
async def start_handler(message: types.Message):
    if message.text == "/start":
        subs = load_subscribers()
        if message.chat.id not in subs:
            subs.append(message.chat.id)
            save_subscribers(subs)
            logging.info(f"📝 Новый подписчик: {message.chat.id}")

        matches = load_matches()
        if matches:
            text = "Вы подписаны на уведомления о матчах Динамо Минск!\n\nДоступные матчи:\n\n"
            for m in matches:
                text += f"📅 {m['date']}\n🏒 {m['title']}\n🎟 <a href='{m['link']}'>Купить билет</a>\n\n"
        else:
            text = "Вы подписаны на уведомления! Пока нет доступных матчей."

        await message.answer(text)

    elif message.text == "/stop":
        subs = load_subscribers()
        if message.chat.id in subs:
            subs.remove(message.chat.id)
            save_subscribers(subs)
            await message.answer("Вы отписались от уведомлений.")
        else:
            await message.answer("Вы не были подписаны.")

# ===============================
# 🌍 ВЕБ-СЕРВЕР (WEBHOOK)
# ===============================
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    asyncio.create_task(monitor_matches())
    logging.info(f"🌍 Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app):
    await bot.delete_webhook()
    logging.info("🧹 Webhook удалён")

async def handle_webhook(request):
    try:
        update = types.Update.model_validate(await request.json())
        await dp.feed_update(bot, update)
        return web.Response(status=200, text="OK")
    except Exception as e:
        logging.error(f"Ошибка в webhook: {e}")
        return web.Response(status=500, text=str(e))

app = web.Application()
app.router.add_post("/webhook", handle_webhook)
app.router.add_get("/", lambda _: web.Response(text="✅ Bot is running"))
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

# ===============================
# 🚀 ЗАПУСК
# ===============================
if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=10000)
