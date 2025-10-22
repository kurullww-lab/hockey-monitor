import os
import json
import asyncio
import logging
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from flask import Flask, request

from aiogram import Bot, Dispatcher

# ---------------------------------------------------------
# 🔧 ЛОГИРОВАНИЕ
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# ⚙️ НАСТРОЙКИ
# ---------------------------------------------------------
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "645388044"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
URL = "https://hcdinamo.by/tickets/"

# Файл состояния матчей
STATE_FILE = "matches.json"

# Flask-приложение для Render
app = Flask(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ---------------------------------------------------------
# 🧩 ФУНКЦИЯ: загрузка предыдущего состояния
# ---------------------------------------------------------
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                logger.warning("⚠️ Ошибка при чтении matches.json, создаю новый")
                return []
    return []


# ---------------------------------------------------------
# 💾 ФУНКЦИЯ: сохранение состояния
# ---------------------------------------------------------
def save_state(matches):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(matches, f, ensure_ascii=False, indent=2)
    logger.info("💾 Состояние матчей сохранено")


# ---------------------------------------------------------
# 🕓 КОРРЕКТНОЕ РАСПОЗНАВАНИЕ ДАТЫ МАТЧА
# ---------------------------------------------------------
def parse_match_date(day_str: str):
    """Парсит дату матча, корректно определяя месяц."""
    try:
        now = datetime.now()
        day_str = day_str.strip()
        parts = day_str.split()

        # Если строка содержит только число и время, например "28 19:00"
        if len(parts) == 2:
            day_part, time_part = parts
            day = int(day_part)
            hour, minute = map(int, time_part.split(":"))

            # Автоопределение месяца
            if now.month == 10:  # Октябрь
                if day >= now.day - 5:
                    month = 10
                else:
                    month = 11
            elif now.month == 11:
                if day < now.day - 5:
                    month = 12
                else:
                    month = 11
            else:
                month = now.month

            date_obj = datetime(now.year, month, day, hour, minute)
            logger.info(f"✅ Дата распарсена: {date_obj.strftime('%d.%m.%Y %H:%M')}")
            return date_obj

        # Если строка уже содержит название месяца
        elif len(parts) == 3:
            day = int(parts[0])
            month_text = parts[1].lower()
            time_part = parts[2]
            hour, minute = map(int, time_part.split(":"))

            month_map = {
                "октября": 10, "ноября": 11, "декабря": 12,
                "января": 1, "февраля": 2, "марта": 3,
                "апреля": 4, "мая": 5, "июня": 6,
                "июля": 7, "августа": 8, "сентября": 9
            }

            month = month_map.get(month_text, now.month)
            date_obj = datetime(now.year, month, day, hour, minute)
            logger.info(f"✅ Дата распарсена: {date_obj.strftime('%d.%m.%Y %H:%M')}")
            return date_obj

    except Exception as e:
        logger.error(f"Ошибка парсинга даты '{day_str}': {e}")
        return None


# ---------------------------------------------------------
# 🌐 ПАРСИНГ САЙТА
# ---------------------------------------------------------
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

    for match in soup.select("a.match-item"):
        title = match.get_text(strip=True)
        if not title:
            continue

        date_tag = match.select_one(".match-day")
        if not date_tag:
            continue

        date_text = date_tag.get_text(strip=True)
        logger.info(f"🔧 Парсим дату: '{date_text}'")

        match_date = parse_match_date(date_text)
        if not match_date:
            continue

        matches.append({
            "title": title,
            "date": match_date.strftime("%Y-%m-%d %H:%M")
        })

    logger.info(f"🎯 Найдено матчей: {len(matches)}")
    return matches


# ---------------------------------------------------------
# 📢 УВЕДОМЛЕНИЕ В ТЕЛЕГРАМ
# ---------------------------------------------------------
async def notify_new_matches(new_matches):
    if not new_matches:
        return

    text = "🏒 Новые матчи!\n\n"
    for m in new_matches:
        text += f"📅 {m['date']}\n⚔ {m['title']}\n\n"

    try:
        await bot.send_message(ADMIN_CHAT_ID, text)
        logger.info(f"✅ Отправлено {len(new_matches)} новых матчей администратору")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления: {e}")


# ---------------------------------------------------------
# 🔄 ОСНОВНОЙ ЦИКЛ МОНИТОРИНГА
# ---------------------------------------------------------
async def monitor():
    logger.info("🚀 Запуск мониторинга")
    prev_matches = load_state()
    prev_titles = {m["title"] for m in prev_matches}

    while True:
        matches = await fetch_matches()
        new_titles = {m["title"] for m in matches}

        added = [m for m in matches if m["title"] not in prev_titles]
        removed = [m for m in prev_matches if m["title"] not in new_titles]

        if added or removed:
            logger.info(f"✨ Изменения: +{len(added)}, -{len(removed)}")
            await notify_new_matches(added)
            save_state(matches)
            prev_matches = matches
            prev_titles = new_titles
        else:
            logger.info("⏳ Новых матчей нет")

        await asyncio.sleep(CHECK_INTERVAL)


# ---------------------------------------------------------
# 🌐 FLASK РОУТЫ (Render)
# ---------------------------------------------------------
@app.route("/")
def home():
    return "✅ Hockey Monitor Bot работает!"


@app.route("/health")
def health():
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    return "Webhook OK", 200


# ---------------------------------------------------------
# ▶️ ЗАПУСК
# ---------------------------------------------------------
if __name__ == "__main__":
    logger.info("🌐 Запуск веб-сервера на порту 5000...")
    loop = asyncio.get_event_loop()
    loop.create_task(monitor())
    app.run(host="0.0.0.0", port=5000)
