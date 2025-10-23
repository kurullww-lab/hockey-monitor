import asyncio
import logging
import threading
import os
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from flask import Flask

# ==============================
# 🔧 Настройки
# ==============================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Токен из Render env
MATCHES_URL = "https://hcdinamo.by/tickets/"
CHECK_INTERVAL = 300  # каждые 5 минут

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("hockey_monitor")

# ==============================
# 🚀 Flask Web Server
# ==============================
app = Flask(__name__)

@app.route('/')
def index():
    return "✅ Hockey Monitor Bot is running!"

# ==============================
# 🤖 Telegram Bot
# ==============================
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

subscribers = set()
last_matches = set()

# ==============================
# 🏒 Парсер матчей
# ==============================
def fetch_matches():
    try:
        response = requests.get(MATCHES_URL, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        matches = []
        for match in soup.select("a.match-item"):
            title = match.select_one(".match-title")
            date_day = match.select_one(".match-day")
            date_month = match.select_one(".match-month")
            time = match.select_one(".match-times")
            ticket_link = match.get("href")

            # Формируем удобный текст
            title_text = title.get_text(strip=True) if title else "Без названия"
            date_text = f"{date_day.get_text(strip=True)} {date_month.get_text(strip=True)} {time.get_text(strip=True)}"
            full_link = ticket_link if ticket_link.startswith("http") else f"https://hcdinamo.by{ticket_link}"

            matches.append({
                "title": title_text,
                "date": date_text,
                "link": full_link
            })

        logger.info(f"🎯 Найдено матчей: {len(matches)}")
        return matches
    except Exception as e:
        logger.error(f"Ошибка при загрузке матчей: {e}")
        return []

# ==============================
# 📢 Команда /start
# ==============================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    subscribers.add(message.chat.id)
    matches = fetch_matches()

    if not matches:
        await message.answer("Вы подписаны на уведомления о матчах Динамо Минск!\n\nПока нет доступных матчей.\n🏒 Мониторинг запущен!")
        return

    text_lines = []
    for m in matches:
        text_lines.append(f"📅 <b>{m['date']}</b>\n🏒 {m['title']}\n🎟 <a href='{m['link']}'>Купить билет</a>")
    text = "\n\n".join(text_lines)

    await message.answer(f"Вы подписаны на уведомления о матчах Динамо Минск!\n\n{text}\n\n🏒 Мониторинг запущен!")

# ==============================
# 🔁 Проверка обновлений
# ==============================
async def monitor_matches():
    global last_matches
    await asyncio.sleep(5)

    while True:
        try:
            logger.info("🔄 Проверка матчей...")
            matches = fetch_matches()
            if not matches:
                logger.info("❕ Нет матчей для отображения.")
            else:
                current_set = {m['title'] for m in matches}

                # Проверяем на изменения (новые или удалённые матчи)
                if current_set != last_matches:
                    added = current_set - last_matches
                    removed = last_matches - current_set
                    last_matches = current_set

                    text_parts = []
                    if added:
                        text_parts.append("➕ Новые матчи:\n" + "\n".join(f"🏒 {t}" for t in added))
                    if removed:
                        text_parts.append("➖ Удалённые матчи:\n" + "\n".join(f"🚫 {t}" for t in removed))

                    if subscribers:
                        for chat_id in subscribers:
                            await bot.send_message(chat_id, "\n\n".join(text_parts))
                        logger.info(f"📊 Итог отправки: ✅ {len(subscribers)}")
                    else:
                        logger.info("❕ Нет подписчиков для уведомления.")
                else:
                    logger.info("✅ Изменений нет.")
        except Exception as e:
            logger.error(f"Ошибка в monitor_matches: {e}")

        logger.info(f"⏰ Следующая проверка через {CHECK_INTERVAL // 60} мин.")
        await asyncio.sleep(CHECK_INTERVAL)

# ==============================
# 🚀 Запуск Flask + Bot
# ==============================
def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

async def main():
    # Удаляем старый webhook (чтобы не было конфликтов с polling)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🌐 Webhook удалён, включен polling режим.")

    # Запускаем Flask в отдельном потоке
    threading.Thread(target=run_flask, daemon=True).start()

    # Запускаем мониторинг
    asyncio.create_task(monitor_matches())

    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
