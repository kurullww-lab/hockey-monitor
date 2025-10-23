import os
import json
import asyncio
import logging
import aiohttp
from aiogram import Bot
from bs4 import BeautifulSoup
from flask import Flask, request
import re
from datetime import datetime

# === НАСТРОЙКИ ===
URL = "https://hcdinamo.by/tickets/"
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))  # 5 минут по умолчанию
DATA_FILE = "matches.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

bot = Bot(token=TELEGRAM_TOKEN)
app = Flask(__name__)

# === ЛОГИ ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# === УТИЛИТЫ ===
def normalize_text(text):
    return re.sub(r"\s+", " ", text.strip())

def load_previous_matches():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_matches(matches):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(matches, f, ensure_ascii=False, indent=2)

def same_match(a, b):
    return a["title"] == b["title"] and a["date"] == b["date"]

# === ПАРСИНГ ===
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

# === УВЕДОМЛЕНИЯ ===
async def broadcast(text, users):
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
    logger.info(f"📊 Итог отправки: ✅ {success} успешно, ❌ {failed} ошибок")

# === МОНИТОРИНГ ===
async def monitor():
    logger.info("🚀 Запуск мониторинга Dinamo Tickets")
    prev_matches = load_previous_matches()
    logger.info(f"📂 Загружено предыдущих матчей: {len(prev_matches)}")

    while True:
        logger.info(f"🔄 Проверка в {datetime.now().strftime('%H:%M:%S')}...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(URL) as resp:
                    html = await resp.text()

            matches = parse_matches(html)
            logger.info(f"🎯 Найдено матчей: {len(matches)}")

            if not matches:
                logger.warning("⚠️ Не удалось получить список матчей")
            else:
                added = [m for m in matches if not any(same_match(m, p) for p in prev_matches)]
                removed = [p for p in prev_matches if not any(same_match(p, m) for m in matches)]

                if added or removed:
                    msg = []
                    if added:
                        msg.append("➕ Добавлены матчи:\n" + "\n".join(
                            f"• [{m['title']} ({m['date']})]({m['url']})" for m in added
                        ))
                    if removed:
                        msg.append("➖ Удалены матчи:\n" + "\n".join(
                            f"• [{m['title']} ({m['date']})]({m['url']})" for m in removed
                        ))

                    full_msg = "\n\n".join(msg)
                    logger.info(full_msg)
                    await broadcast(full_msg, [TELEGRAM_CHAT_ID])
                    prev_matches = matches
                    save_matches(matches)
                else:
                    logger.info("✅ Изменений нет")

        except Exception as e:
            logger.error(f"❌ Ошибка парсинга: {e}")

        logger.info(f"⏰ Следующая проверка через {CHECK_INTERVAL // 60} мин.")
        await asyncio.sleep(CHECK_INTERVAL)

# === FLASK СЕРВЕР ===
@app.route("/")
def home():
    return "🏒 Hockey Monitor Bot работает!"

@app.route("/health")
def health():
    return "OK", 200

# === ЗАПУСК ===
if __name__ == "__main__":
    import threading

    def run_flask():
        port = int(os.getenv("PORT", 10000))
        logger.info(f"🌐 Запуск веб-сервера на порту {port}...")
        app.run(host="0.0.0.0", port=port)

    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(monitor())
