import os
import time
import asyncio
import logging
import requests
from flask import Flask
from bs4 import BeautifulSoup
from datetime import datetime
from aiogram import Bot

# ==========================
# 🔧 Конфигурация
# ==========================

URL = "https://hcdinamo.by/tickets/"
FALLBACK_URL = "https://r.jina.ai/http://hcdinamo.by/tickets/"
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)

# ==========================
# 🧩 Вспомогательные функции
# ==========================

def parse_match_date(text: str):
    """Преобразует дату формата '22.11.2025 19:00' в datetime"""
    try:
        return datetime.strptime(text.strip(), "%d.%m.%Y %H:%M")
    except Exception:
        return None


def get_html(url):
    """Загружает HTML с указанного URL с заголовками браузера"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://google.com/",
        "Connection": "keep-alive"
    }

    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error(f"❌ Ошибка при загрузке {url}: {e}")
        return ""


async def fetch_matches():
    """Загружает HTML страницы и парсит матчи (с fallback на зеркало)"""
    logger.info("🌍 Загружаем страницу...")

    html = get_html(URL)

    # Проверка на Cloudflare
    if "cf-challenge" in html or "Cloudflare" in html or len(html) < 5000:
        logger.warning("⚠️ Cloudflare блокирует парсинг — пробуем через зеркало...")
        html = get_html(FALLBACK_URL)

    if not html:
        logger.error("❌ Не удалось получить HTML ни с основного сайта, ни с зеркала")
        return []

    soup = BeautifulSoup(html, "html.parser")
    elements = soup.select("a.match-item")
    logger.info(f"🎯 Найдено элементов a.match-item: {len(elements)}")

    matches = []
    for match in elements:
        title = match.get_text(strip=True)
        date_tag = match.select_one(".match-day")

        if not title or not date_tag:
            continue

        date_text = date_tag.get_text(strip=True)
        match_date = parse_match_date(date_text)
        if not match_date:
            continue

        matches.append({
            "title": title,
            "date": match_date.strftime("%Y-%m-%d %H:%M")
        })

    logger.info(f"🎯 Найдено матчей: {len(matches)}")
    return matches


async def send_telegram_message(text: str):
    """Отправка сообщения в Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ TELEGRAM_TOKEN или TELEGRAM_CHAT_ID не заданы — уведомление не отправлено")
        return

    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
        logger.info(f"📩 Отправлено уведомление: {text}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки в Telegram: {e}")


async def monitor_matches():
    """Основной цикл мониторинга"""
    logger.info("🚀 Запуск мониторинга Dinamo Tickets (requests-only версия)")

    previous = []
    while True:
        logger.info(f"🔄 Проверка в {datetime.now().strftime('%H:%M:%S')}...")
        current = await fetch_matches()

        if not current:
            logger.warning("⚠️ Не удалось получить список матчей")
        elif current != previous:
            if not previous:
                logger.info(f"📂 Загружено предыдущих матчей: 0")
            else:
                logger.info("🆕 Обновление найдено! Отправляем уведомление...")
                await send_telegram_message("🆕 Изменения на сайте Dinamo Tickets!")
            previous = current
        else:
            logger.info("✅ Изменений нет")

        logger.info(f"⏰ Следующая проверка через {CHECK_INTERVAL // 60} мин.\n")
        await asyncio.sleep(CHECK_INTERVAL)

# ==========================
# 🌐 Flask веб-сервер
# ==========================

@app.route("/")
def index():
    return "✅ Dinamo Tickets Monitor is running."

@app.route("/health")
def health():
    return {"status": "ok"}, 200


# ==========================
# 🚀 Запуск
# ==========================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    logger.info(f"🌐 Запуск веб-сервера на порту {port}...")

    loop = asyncio.get_event_loop()
    loop.create_task(monitor_matches())

    from threading import Thread
    def run_flask():
        app.run(host="0.0.0.0", port=port)
    Thread(target=run_flask).start()

    loop.run_forever()
