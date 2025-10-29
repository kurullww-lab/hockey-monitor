import os
import asyncio
import logging
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message
from flask import Flask
from threading import Thread

# 🔧 Настройка логов
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
URL = "https://hcdinamo.by/match/"

# 🤖 Инициализация бота
bot = Bot(token=BOT_TOKEN, default=types.DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# 🧩 Глобальные данные
subscribers = set()
last_matches = []


# ==============================
# 🔍 Парсер матчей
# ==============================
def fetch_matches():
    try:
        response = requests.get(URL, timeout=15)
        if response.status_code != 200:
            logging.warning(f"⚠️ Ошибка загрузки ({response.status_code})")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        match_blocks = soup.find_all("div", class_="match-title")
        logging.info(f"🎯 Найдено матчей: {len(match_blocks)}")

        matches = []
        for block in match_blocks:
            title = block.get_text(strip=True)
            parent = block.find_parent("a")
            link = parent["href"] if parent and parent.has_attr("href") else URL
            date_el = block.find_previous("div", class_="match-date")
            time_el = block.find_next("div", class_="match-time")

            matches.append({
                "title": title,
                "date": date_el.get_text(strip=True) if date_el else "",
                "time": time_el.get_text(strip=True) if time_el else "",
                "link": link,
            })

        return matches

    except Exception as e:
        logging.error(f"Ошибка при парсинге: {e}")
        return []


# ==============================
# 📢 Отправка уведомлений
# ==============================
async def notify_all(bot, added_matches, removed_matches, subscribers):
    if not added_matches and not removed_matches:
        return

    added_text = ""
    removed_text = ""

    # Новые матчи
    if added_matches:
        added_text = "➕ Добавлено:\n" + "\n\n".join(
            f"📅 {m['date']}\n🏒 {m['title']}\n🕒 {m['time']}\n🎟 <a href='{m['link']}'>Купить билет</a>"
            for m in added_matches
        )

    # Удалённые (начавшиеся) матчи — без ссылки
    if removed_matches:
        removed_text = "➖ Удалено:\n" + "\n\n".join(
            f"📅 {m['date']}\n🏒 {m['title']}\n🕒 {m['time']}"
            for m in removed_matches
        )

    text = "Обновления матчей:\n\n" + "\n\n".join(filter(None, [added_text, removed_text]))

    for chat_id in subscribers:
        try:
            await bot.send_message(chat_id, text, disable_web_page_preview=True)
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение {chat_id}: {e}")


# ==============================
# 🕒 Мониторинг изменений
# ==============================
async def monitor_matches():
    global last_matches
    logging.info("🏁 Мониторинг матчей запущен!")
    last_matches = fetch_matches()

    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        current_matches = fetch_matches()
        if not current_matches:
            logging.info("⚠️ Матчи не найдены при проверке")
            continue

        added = [m for m in current_matches if m not in last_matches]
        removed = [m for m in last_matches if m not in current_matches]

        if added or removed:
            logging.info(f"⚡ Изменения: добавлено {len(added)}, удалено {len(removed)}")
            await notify_all(bot, added, removed, subscribers)
            last_matches = current_matches
        else:
            logging.info("✅ Изменений нет")


# ==============================
# 🚀 Команда /start
# ==============================
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    subscribers = load_subscribers()

    if user_id not in subscribers:
        subscribers.append(user_id)
        save_subscribers(subscribers)
        logger.info(f"📝 Новый подписчик: {user_id}")

    await message.answer("✅ Вы подписаны на уведомления о матчах Динамо Минск!")

    # Загружаем актуальные матчи
    matches = fetch_matches()
    logger.info(f"Возвращено матчей из fetch_matches: {len(matches)}")

    # Отправляем список пользователю
    if matches:
        await notify_all(matches, [], [user_id])
    else:
        await message.answer("❌ Сейчас нет доступных матчей.")


# ==============================
# 🌐 Flask (Render healthcheck)
# ==============================
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ Hockey Monitor is running"

def run_flask():
    app.run(host="0.0.0.0", port=10000)


# ==============================
# 🔄 Основной запуск
# ==============================
async def main():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    await asyncio.sleep(2)
    asyncio.create_task(monitor_matches())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
