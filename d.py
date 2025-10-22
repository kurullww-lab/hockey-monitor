import os
import time
import logging
import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from aiogram import Bot
from flask import Flask

# --------------------------------------------
# 🔧 Настройки
# --------------------------------------------
URL = "https://hcdinamo.by/tickets/"
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8416784515:AAG1yGWcgm9gGFPJLodfLvEJrtmIFVJjsu8")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE = "matches.txt"

# --------------------------------------------
# ⚙️ Логирование
# --------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger()

# --------------------------------------------
# 🧠 Вспомогательные функции
# --------------------------------------------
def load_previous_matches():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(f.read().splitlines())
    return set()


def save_current_matches(matches):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        for match in matches:
            f.write(f"{match}\n")


async def send_telegram_message(bot, message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ TELEGRAM_TOKEN или TELEGRAM_CHAT_ID не заданы, уведомление не отправлено")
        return
    try:
        await bot.send_message(TELEGRAM_CHAT_ID, message)
        logger.info(f"📨 Уведомление отправлено в Telegram: {message}")
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения в Telegram: {e}")

# --------------------------------------------
# 🗓️ Парсинг даты (учёт месяца)
# --------------------------------------------
def parse_match_date(day_str: str, current_month: int):
    """Парсит дату, учитывая текущий месяц"""
    try:
        now = datetime.now()
        parts = day_str.strip().split()
        if len(parts) == 2:
            day_part, time_part = parts
            day = int(day_part)
            hour, minute = map(int, time_part.split(":"))
            date_obj = datetime(now.year, current_month, day, hour, minute)
            logger.info(f"✅ Дата распарсена: {date_obj.strftime('%d.%m.%Y %H:%M')}")
            return date_obj
    except Exception as e:
        logger.error(f"Ошибка парсинга даты '{day_str}': {e}")
        return None


# --------------------------------------------
# 🌍 Получение матчей с сайта
# --------------------------------------------
async def fetch_matches():
    logger.info("🌍 Загружаем страницу...")
    try:
        response = requests.get(URL, timeout=15)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"❌ Ошибка при загрузке страницы: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    matches = []

    # Месяцы
    current_month = datetime.now().month
    month_map = {
        "январь": 1, "февраль": 2, "март": 3, "апрель": 4, "май": 5,
        "июнь": 6, "июль": 7, "август": 8, "сентябрь": 9,
        "октябрь": 10, "ноябрь": 11, "декабрь": 12
    }

    for element in soup.select(".matches-list > *"):
        text = element.get_text(strip=True).lower()

        # Если это заголовок месяца
        for rus_month, num in month_map.items():
            if rus_month in text:
                current_month = num
                logger.info(f"📅 Обнаружен новый месяц: {rus_month} ({num})")
                break

        # Если это матч
        if element.name == "a" and "match-item" in element.get("class", []):
            title = element.get_text(strip=True)
            date_tag = element.select_one(".match-day")
            if not date_tag:
                continue

            date_text = date_tag.get_text(strip=True)
            logger.info(f"🔧 Парсим дату: '{date_text}' (месяц {current_month})")

            match_date = parse_match_date(date_text, current_month)
            if not match_date:
                continue

            matches.append({
                "title": title,
                "date": match_date.strftime("%Y-%m-%d %H:%M")
            })

    logger.info(f"🎯 Найдено матчей: {len(matches)}")
    return matches


# --------------------------------------------
# 🔁 Основной цикл мониторинга
# --------------------------------------------
async def monitor():
    logger.info("🚀 Запуск мониторинга Dinamo Tickets (requests-only версия)")
    bot = Bot(token=TELEGRAM_TOKEN)
    previous_matches = load_previous_matches()
    logger.info(f"📂 Загружено предыдущих матчей: {len(previous_matches)}")

    while True:
        logger.info(f"🔄 Проверка в {datetime.now().strftime('%H:%M:%S')}...")
        matches = await fetch_matches()
        current_titles = {m['title'] for m in matches if 'title' in m}

        new_matches = current_titles - previous_matches
        if new_matches:
            logger.info(f"🆕 Найдены новые матчи: {len(new_matches)}")
            message = "🏒 Новые матчи доступны:\n" + "\n".join(new_matches)
            await send_telegram_message(bot, message)
            save_current_matches(current_titles)
            previous_matches = current_titles
        else:
            logger.info("✅ Изменений нет")

        logger.info(f"⏰ Следующая проверка через {CHECK_INTERVAL // 60} мин.")
        await asyncio.sleep(CHECK_INTERVAL)


# --------------------------------------------
# 🌐 Flask web-сервер (для Render ping)
# --------------------------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Dinamo Tickets Monitor is running!"

@app.route("/health")
def health():
    logger.info("🏓 Авто-пинг: 200")
    return "OK", 200


# --------------------------------------------
# 🚀 Запуск приложения
# --------------------------------------------
if __name__ == "__main__":
    from threading import Thread

    # Отдельный поток для Flask
    def run_flask():
        port = int(os.environ.get("PORT", 5000))
        logger.info(f"🌐 Запуск веб-сервера на порту {port}...")
        app.run(host="0.0.0.0", port=port)

    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Основной цикл мониторинга
    asyncio.run(monitor())
