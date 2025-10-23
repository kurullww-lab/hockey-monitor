import os
import json
import asyncio
import logging
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from bs4 import BeautifulSoup
from flask import Flask
import re
from datetime import datetime
import threading

# === НАСТРОЙКИ ===
URL = "https://hcdinamo.by/tickets/"
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))  # каждые 5 минут
DATA_FILE = "matches.json"
SUBSCRIBERS_FILE = "subscribers.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
app = Flask(__name__)

# === ЛОГИ ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# === УТИЛИТЫ ===
def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_text(text):
    return re.sub(r"\s+", " ", text.strip())


def same_match(a, b):
    return a["title"] == b["title"] and a["date"] == b["date"]


# === ПОДПИСЧИКИ ===
def get_subscribers():
    return load_json(SUBSCRIBERS_FILE, [])


def add_subscriber(user_id):
    subs = get_subscribers()
    if user_id not in subs:
        subs.append(user_id)
        save_json(SUBSCRIBERS_FILE, subs)
        return True
    return False


# === ПАРСИНГ МАТЧЕЙ ===
def parse_matches(html):
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("a.match-item")
    logger.info(f"🎯 Найдено элементов a.match-item: {len(items)}")

    matches = []
    for item in items:
        title_elem = item.select_one(".match-title, .match__title, h3, .title")
        title = normalize_text(title_elem.get_text()) if title_elem else ""

        date_elem = item.select_one(".match-day, .match-date, .match__info, time")
        date_text = normalize_text(date_elem.get_text()) if date_elem else ""

        if not date_text:
            full_text = item.get_text(" ", strip=True)
            m = re.search(r"(\d{1,2}\s[а-яА-Я]+|\d{1,2}\.\d{1,2}\.\d{4}).*?(\d{1,2}:\d{2})", full_text)
            if m:
                date_text = f"{m.group(1)} {m.group(2)}"

        href = item.get("href", "")
        if href and href.startswith("/"):
            href = f"https://hcdinamo.by{href}"

        if title and date_text:
            matches.append({
                "title": title,
                "date": date_text,
                "url": href or URL
            })
    return matches


# === РАССЫЛКА ===
async def broadcast(text):
    users = get_subscribers()
    success, failed = 0, 0
    for user_id in users:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            success += 1
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при отправке {user_id}: {e}")
            failed += 1
    logger.info(f"📊 Итог отправки: ✅ {success} / ❌ {failed}")


# === МОНИТОРИНГ ===
async def monitor():
    logger.info("🚀 Запуск мониторинга Dinamo Tickets")
    prev_matches = load_json(DATA_FILE, [])
    logger.info(f"📂 Загружено предыдущих матчей: {len(prev_matches)}")

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(URL) as resp:
                    html = await resp.text()

            matches = parse_matches(html)
            logger.info(f"🎯 Найдено матчей: {len(matches)}")

            added = [m for m in matches if not any(same_match(m, p) for p in prev_matches)]
            removed = [p for p in prev_matches if not any(same_match(p, m) for m in matches)]

            if added or removed:
                msg_parts = []
                if added:
                    msg_parts.append("➕ *Добавлены матчи:*\n" + "\n".join(
                        f"• [{m['title']} ({m['date']})]({m['url']})" for m in added
                    ))
                if removed:
                    msg_parts.append("➖ *Удалены матчи:*\n" + "\n".join(
                        f"• {m['title']} ({m['date']})" for m in removed
                    ))

                message = "\n\n".join(msg_parts)
                await broadcast(message)
                prev_matches = matches
                save_json(DATA_FILE, matches)
            else:
                logger.info("✅ Изменений нет")

        except Exception as e:
            logger.error(f"❌ Ошибка мониторинга: {e}")

        logger.info(f"⏰ Следующая проверка через {CHECK_INTERVAL // 60} мин.")
        await asyncio.sleep(CHECK_INTERVAL)


# === TELEGRAM ХЕНДЛЕРЫ ===
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    added = add_subscriber(message.chat.id)
    if added:
        await message.answer("✅ Вы подписались на уведомления о матчах Dinamo Minsk!")
        await bot.send_message(message.chat.id, "Я пришлю уведомление, когда появятся новые матчи 🎯")
    else:
        await message.answer("Вы уже подписаны 🔔")


@dp.message(Command("unsubscribe"))
async def unsubscribe_handler(message: types.Message):
    subs = get_subscribers()
    if message.chat.id in subs:
        subs.remove(message.chat.id)
        save_json(SUBSCRIBERS_FILE, subs)
        await message.answer("❌ Вы отписались от уведомлений.")
    else:
        await message.answer("Вы не были подписаны.")


@dp.message(Command("matches"))
async def matches_handler(message: types.Message):
    matches = load_json(DATA_FILE, [])
    if not matches:
        await message.answer("Нет доступных матчей.")
        return
    text = "*Текущие матчи:*\n" + "\n".join(
        f"• [{m['title']} ({m['date']})]({m['url']})" for m in matches
    )
    await message.answer(text, parse_mode="Markdown", disable_web_page_preview=True)


# === FLASK ДЛЯ Render ===
@app.route("/")
def home():
    return "🏒 Hockey Monitor Bot активен!", 200


@app.route("/health")
def health():
    return "OK", 200


# === ЗАПУСК ===
if __name__ == "__main__":
    def run_flask():
        port = int(os.getenv("PORT", 10000))
        logger.info(f"🌐 Flask запущен на порту {port}")
        app.run(host="0.0.0.0", port=port)

    threading.Thread(target=run_flask, daemon=True).start()

    async def main():
        asyncio.create_task(monitor())
        await dp.start_polling(bot)

    asyncio.run(main())
