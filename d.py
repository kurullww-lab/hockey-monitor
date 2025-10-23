import asyncio
import logging
import threading
import os
import requests
import time
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from flask import Flask

# ==============================
# 🔧 Настройки
# ==============================
# Используем правильное имя переменной
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")  # Теперь берем из TELEGRAM_TOKEN

# Проверяем, что токен установлен
if not BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN environment variable is not set! Please check Render.com environment variables.")

# Используем другие переменные из окружения
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))  # 5 минут по умолчанию
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Опционально для тестов
RENDER_URL = os.getenv("RENDER_URL", "https://hockey-monitor.onrender.com")

MATCHES_URL = "https://hcdinamo.by/tickets/"

# Словарь для преобразования месяцев
MONTHS = {
    'янв': 'января', 'фев': 'февраля', 'мар': 'марта', 'апр': 'апреля',
    'май': 'мая', 'июн': 'июня', 'июл': 'июля', 'авг': 'августа',
    'сен': 'сентября', 'окт': 'октября', 'ноя': 'ноября', 'дек': 'декабря'
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("hockey_monitor")

# ==============================
# 🚀 Flask Web Server
# ==============================
app = Flask(__name__)

@app.route('/')
def index():
    return "✅ Hockey Monitor Bot is running!"

@app.route('/health')
def health():
    return "OK", 200

# ==============================
# 🤖 Telegram Bot
# ==============================
try:
    # Новый синтаксис для aiogram 3.17.0+
    bot = Bot(
        token=BOT_TOKEN, 
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    logger.info("✅ Bot initialized successfully")
except Exception as e:
    logger.error(f"❌ Failed to initialize bot: {e}")
    raise

subscribers = set()
last_matches = set()

# ==============================
# 🏒 Парсер матчей
# ==============================
def format_date(day, month, time):
    """Форматирует дату в красивый вид: 28 ноября, Пт 19:00"""
    try:
        # Преобразуем месяц в полный формат
        month_lower = month.lower() if month else ''
        full_month = MONTHS.get(month_lower, month)
        
        # Определяем день недели (если нужно)
        # Пока используем существующий формат, но можно добавить определение дня недели
        if day and full_month and time:
            return f"{day} {full_month}, {time}"
        elif day and full_month:
            return f"{day} {full_month}"
        else:
            return f"{day if day else '?'} {month if month else '?'} {time if time else '?'}"
    except Exception as e:
        logger.error(f"Ошибка форматирования даты: {e}")
        return f"{day if day else '?'} {month if month else '?'} {time if time else '?'}"

def fetch_matches():
    try:
        response = requests.get(MATCHES_URL, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        matches = []
        match_elements = soup.select("a.match-item")
        logger.info(f"🎯 Найдено элементов a.match-item: {len(match_elements)}")
        
        for match in match_elements:
            title = match.select_one(".match-title")
            date_day = match.select_one(".match-day")
            date_month = match.select_one(".match-month")
            time = match.select_one(".match-times")
            ticket_link = match.get("href")

            # Формируем удобный текст
            title_text = title.get_text(strip=True) if title else "Без названия"
            
            # Получаем текстовые значения
            day_text = date_day.get_text(strip=True) if date_day else None
            month_text = date_month.get_text(strip=True) if date_month else None
            time_text = time.get_text(strip=True) if time else None
            
            # Форматируем дату
            date_text = format_date(day_text, month_text, time_text)
            
            if ticket_link:
                full_link = ticket_link if ticket_link.startswith("http") else f"https://hcdinamo.by{ticket_link}"
            else:
                full_link = "https://hcdinamo.by/tickets/"

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
    logger.info(f"📝 Новый подписчик: {message.chat.id}")
    
    matches = fetch_matches()

    if not matches:
        await message.answer("Вы подписаны на уведомления о матчах Динамо Минск!\n\nПока нет доступных матчей.\n🏒 Мониторинг запущен!")
        return

    text_lines = ["Вы подписаны на уведомления о матчах Динамо Минск!\n\nДоступные матчи:"]
    for m in matches:
        text_lines.append(f"📅 <b>{m['date']}</b>\n🏒 {m['title']}\n🎟 <a href='{m['link']}'>Купить билет</a>")
    text = "\n\n".join(text_lines)
    text += "\n\n🏒 Мониторинг запущен! Вы будете получать уведомления о новых матчах."

    await message.answer(text)

# ==============================
# 🔁 Проверка обновлений
# ==============================
async def monitor_matches():
    global last_matches
    await asyncio.sleep(5)

    while True:
        try:
            logger.info("🔄 Проверка...")
            matches = fetch_matches()
            if not matches:
                logger.info("❕ Нет матчей для отображения.")
            else:
                current_set = {f"{m['title']}|{m['date']}" for m in matches}

                # Проверяем на изменения (новые или удалённые матчи)
                if current_set != last_matches:
                    added = current_set - last_matches
                    removed = last_matches - current_set
                    last_matches = current_set

                    if added or removed:
                        text_parts = []
                        if added:
                            added_titles = [item.split('|')[0] for item in added]
                            text_parts.append("➕ <b>Новые матчи:</b>\n" + "\n".join(f"🏒 {t}" for t in added_titles))
                        if removed:
                            removed_titles = [item.split('|')[0] for item in removed]
                            text_parts.append("➖ <b>Удалённые матчи:</b>\n" + "\n".join(f"🚫 {t}" for t in removed_titles))

                        if subscribers:
                            for chat_id in list(subscribers):
                                try:
                                    await bot.send_message(chat_id, "\n\n".join(text_parts))
                                except Exception as e:
                                    logger.error(f"❌ Не удалось отправить сообщение {chat_id}: {e}")
                                    subscribers.discard(chat_id)
                            logger.info(f"📊 Уведомления отправлены: ✅ {len(subscribers)} подписчиков")
                        else:
                            logger.info("❕ Нет подписчиков для уведомления")
                    else:
                        logger.info("✅ Изменений нет")
                else:
                    logger.info("✅ Изменений нет")

        except Exception as e:
            logger.error(f"❌ Ошибка в monitor_matches: {e}")

        logger.info(f"⏰ Следующая проверка через {CHECK_INTERVAL // 60} мин.")
        await asyncio.sleep(CHECK_INTERVAL)

# ==============================
# 🫀 Keep-Alive механизм
# ==============================
def keep_alive():
    """Отправляет запросы каждые 14 минут чтобы сервис не засыпал на Render.com"""
    time.sleep(30)  # Ждем 30 секунд после старта
    
    while True:
        try:
            response = requests.get(f"{RENDER_URL}/health", timeout=10)
            if response.status_code == 200:
                logger.info("🫀 Keep-alive request sent - service is awake")
            else:
                logger.warning(f"🫀 Keep-alive got status: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Keep-alive failed: {e}")
        
        # Ждем 14 минут (840 секунд) - меньше чем 15 минут лимит Render.com
        time.sleep(840)

# ==============================
# 🚀 Запуск Flask + Bot
# ==============================
def run_flask():
    port = int(os.getenv("PORT", 10000))
    logger.info(f"🌐 Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port)

async def main():
    try:
        # Запускаем Keep-Alive в отдельном потоке
        keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
        keep_alive_thread.start()
        logger.info("✅ Keep-alive thread started")

        # Удаляем старый webhook (чтобы не было конфликтов с polling)
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("🌐 Webhook удалён, включен polling режим.")

        # Запускаем Flask в отдельном потоке
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        logger.info("✅ Flask server started")

        # Запускаем мониторинг
        asyncio.create_task(monitor_matches())
        logger.info("✅ Match monitoring started")

        # Запускаем бота
        logger.info("✅ Start polling")
        await dp.start_polling(bot)

    except Exception as e:
        logger.error(f"❌ Fatal error in main: {e}")
        raise

if __name__ == "__main__":
    logger.info("🚀 Starting Hockey Monitor Bot...")
    asyncio.run(main())
