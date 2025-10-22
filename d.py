import os
import re
import time
import json
import asyncio
import logging
import requests
from datetime import datetime
from flask import Flask
from bs4 import BeautifulSoup
from aiogram import Bot

# =============================
# 🔧 Конфигурация
# =============================

URL = "https://hcdinamo.by/tickets/"
FALLBACK_URL = "https://r.jina.ai/http://hcdinamo.by/tickets/"
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)

# =============================
# 🧩 Парсинг матчей
# =============================

def get_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки HTML: {e}")
        return ""


def normalize_text(text):
    return re.sub(r"\s+", " ", text.strip())


def parse_matches(html):
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("a.match-item")
    logger.info(f"🎯 Найдено элементов a.match-item: {len(items)}")

    matches = []
    for item in items:
        # Название матча
        title_elem = item.select_one(".match-title, .match__title, h3, .title")
        title = normalize_text(title_elem.get_text()) if title_elem else ""

        # Дата и время
        date_elem = item.select_one(".match-day, .match-date, .match__info, time")
        date_text = normalize_text(date_elem.get_text()) if date_elem else ""

        # Попытка вытащить дату из общего текста (если сайт изменил структуру)
        if not date_text:
            full_text = item.get_text(" ", strip=True)
            m = re.search(r"(\d{1,2}\s[а-яА-Я]+|\d{1,2}\.\d{1,2}\.\d{4}).*?(\d{1,2}:\d{2})", full_text)
            if m:
                date_text = f"{m.group(1)} {m.group(2)}"

        # Ссылка
        href = item.get("href", "")
        if href and href.startswith("/"):
            href = f"https://hcdinamo.by{href}"

        # Фильтрация
        if title and date_text:
            matches.append({
                "title": title,
                "date": date_text,
                "url": href or URL
            })

    return matches


async def fetch_matches():
    html = get_html(URL)

    # fallback, если Cloudflare
    if not html or "cf-challenge" in html or "Cloudflare" in html:
        logger.warning("⚠️ Cloudflare блокирует, пробуем зеркало...")
        html = get_html(FALLBACK_URL)

    if not html:
        logger.error("❌ Не удалось получить HTML")
        return []

    matches = parse_matches(html)
    logger.info(f"✅ Распознано матчей: {len(matches)}")
    for i, m in enumerate(matches, 1):
        logger.info(f"   {i:2d}. {m['title']} — {m['date']}")
    return matches


# =============================
# 💬 Telegram уведомления
# =============================

async def send_message(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ Не заданы TELEGRAM_TOKEN или TELEGRAM_CHAT_ID")
        return
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
        logger.info(f"📩 Отправлено уведомление: {text}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки Telegram: {e}")


# =============================
# 🔁 Мониторинг
# =============================

async def monitor():
    logger.info("🚀 Запуск мониторинга Dinamo Tickets")

    previous = []
    while True:
        logger.info(f"🔄 Проверка в {datetime.now().strftime('%H:%M:%S')}...")
        current = await fetch_matches()

        if not current:
            logger.warning("⚠️ Матчи не получены, повторим позже.")
        else:
            added = [m for m in current if m not in previous]
            removed = [m for m in previous if m not in current]

            if added or removed:
                msg = []
                if added:
                    msg.append("➕ Добавлены матчи:\n" + "\n".join(f"• {m['title']} ({m['date']})" for m in added))
                if removed:
                    msg.append("➖ Удалены матчи:\n" + "\n".join(f"• {m['title']} ({m['date']})" for m in removed))
                await send_message("\n\n".join(msg))
                previous = current
            else:
                logger.info("✅ Изменений нет")

        logger.info(f"⏰ Следующая проверка через {CHECK_INTERVAL // 60} мин.\n")
        await asyncio.sleep(CHECK_INTERVAL)


# =============================
# 🌐 Flask Web
# =============================

@app.route("/")
def index():
    return "✅ Hockey Monitor Bot is running!"

@app.route("/health")
def health():
    return {"status": "ok"}, 200


# =============================
# 🚀 Запуск
# =============================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    logger.info(f"🌐 Запуск Flask на порту {port}")

    loop = asyncio.get_event_loop()
    loop.create_task(monitor())

    from threading import Thread
    Thread(target=lambda: app.run(host="0.0.0.0", port=port)).start()

    loop.run_forever()
