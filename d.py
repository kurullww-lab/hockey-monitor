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
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN environment variable is not set!")

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RENDER_URL = os.getenv("RENDER_URL", "https://hockey-monitor.onrender.com")

MATCHES_URL = "https://hcdinamo.by/tickets/"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("hockey_monitor")

# ОТЛАДОЧНАЯ ИНФОРМАЦИЯ О ВЕРСИИ
CODE_VERSION = "2.2 - FIXED_MONTH_PARSING"
logger.info(f"🔄 Загружена версия кода: {CODE_VERSION}")

app = Flask(__name__)

@app.route('/')
def index():
    return f"✅ Hockey Monitor Bot is running! Version: {CODE_VERSION}"

@app.route('/health')
def health():
    return "OK", 200

@app.route('/version')
def version():
    return f"Version: {CODE_VERSION}", 200

try:
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
last_matches_dict = {}

# ==============================
# 🏒 Парсер матчей
# ==============================
def parse_month_and_day(month_text):
    """Разделяет месяц и день недели из текста 'окт, Пт'"""
    if not month_text:
        return None, None
    
    # Разделяем по запятой
    parts = [part.strip() for part in month_text.split(',')]
    
    if len(parts) >= 2:
        month = parts[0]  # 'окт'
        day_of_week = parts[1]  # 'Пт'
        return month, day_of_week
    else:
        return month_text, None

def format_date(day, month, day_of_week, time):
    """Форматирует дату в красивый вид: 24 октября, Пт 19:00"""
    try:
        # Словарь для преобразования сокращений в полные названия
        month_map = {
            'янв': 'января', 'фев': 'февраля', 'мар': 'марта', 'апр': 'апреля',
            'май': 'мая', 'июн': 'июня', 'июл': 'июля', 'авг': 'августа',
            'сен': 'сентября', 'окт': 'октября', 'ноя': 'ноября', 'дек': 'декабря'
        }
        
        # Преобразуем месяц в полный формат
        full_month = month_map.get(month, month)
        
        # Собираем компоненты даты
        date_parts = []
        
        if day and full_month:
            date_parts.append(f"{day} {full_month}")
        
        if day_of_week:
            date_parts.append(day_of_week)
            
        if time:
            date_parts.append(time)
        
        # Форматируем: "24 октября, Пт 19:00"
        if len(date_parts) >= 2:
            main_date = date_parts[0]
            other_parts = " ".join(date_parts[1:])
            return f"{main_date}, {other_parts}"
        else:
            return " ".join(date_parts) if date_parts else "Дата не указана"
            
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
        
        for i, match in enumerate(match_elements):
            title = match.select_one(".match-title")
            date_day = match.select_one(".match-day")
            date_month = match.select_one(".match-month")
            time = match.select_one(".match-times")
            ticket_link = match.get("href")

            title_text = title.get_text(strip=True) if title else "Без названия"
            
            day_text = date_day.get_text(strip=True) if date_day else None
            month_text = date_month.get_text(strip=True) if date_month else None
            time_text = time.get_text(strip=True) if time else None
            
            # РАЗДЕЛЯЕМ МЕСЯЦ И ДЕНЬ НЕДЕЛИ
            month_only, day_of_week = parse_month_and_day(month_text)
            
            # ОТЛАДКА: логируем что парсим
            logger.info(f"🔍 Матч {i+1}: день='{day_text}', месяц='{month_only}', день_недели='{day_of_week}', время='{time_text}'")
            
            # ФОРМАТИРУЕМ ДАТУ
            date_text = format_date(day_text, month_only, day_of_week, time_text)
            
            if ticket_link:
                full_link = ticket_link if ticket_link.startswith("http") else f"https://hcdinamo.by{ticket_link}"
            else:
                full_link = "https://hcdinamo.by/tickets/"

            match_data = {
                "title": title_text,
                "date": date_text,
                "link": full_link
            }
            matches.append(match_data)

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

    # Первое приветственное сообщение
    await message.answer("Вы подписаны на уведомления о матчах Динамо Минск!\n\n🏒 Мониторинг запущен!")

    # Отправляем каждое событие отдельно
    for m in matches:
        text = f"📅 <b>{m['date']}</b>\n🏒 {m['title']}\n🎟 <a href='{m['link']}'>Купить билет</a>"
        await message.answer(text)
        await asyncio.sleep(0.3)  # небольшая пауза, чтобы Telegram не ограничил

# ==============================
# 🔁 Проверка обновлений
# ==============================
async def monitor_matches():
    global last_matches_dict
    await asyncio.sleep(5)

    while True:
        try:
            logger.info("🔄 Проверка...")
            current_matches = fetch_matches()
            
            if not current_matches:
                logger.info("❕ Нет матчей для отображения.")
            else:
                # Создаем словарь текущих матчей для сравнения
                current_dict = {f"{m['title']}|{m['date']}": m for m in current_matches}
                current_keys = set(current_dict.keys())
                last_keys = set(last_matches_dict.keys())

                # Находим изменения
                added_keys = current_keys - last_keys
                removed_keys = last_keys - current_keys

                if added_keys or removed_keys:
                    logger.info(f"📈 Обнаружены изменения: +{len(added_keys)}, -{len(removed_keys)}")

                    if subscribers:
                        # ОТДЕЛЬНЫЕ СООБЩЕНИЯ ДЛЯ КАЖДОГО НОВОГО МАТЧА
                        if added_keys:
                            logger.info(f"🎯 Отправляем {len(added_keys)} отдельных сообщений о новых матчах")
                            for key in added_keys:
                                match_data = current_dict[key]
                                message_text = f"➕ <b>Новый матч!</b>\n\n🏒 {match_data['title']}\n📅 {match_data['date']}\n\n🎫 <a href='{match_data['link']}'>Купить билет</a>"
                                
                                for chat_id in list(subscribers):
                                    try:
                                        await bot.send_message(chat_id, message_text)
                                        logger.info(f"📤 Отправлено отдельное сообщение для матча: {match_data['title']}")
                                        await asyncio.sleep(0.3)
                                    except Exception as e:
                                        logger.error(f"❌ Не удалось отправить сообщение {chat_id}: {e}")
                                        subscribers.discard(chat_id)
                            
                            logger.info(f"📊 Уведомления о {len(added_keys)} новых матчах отправлены")

                        # ОТДЕЛЬНЫЕ СООБЩЕНИЯ ДЛЯ КАЖДОГО ПРОШЕДШЕГО/ОТМЕНЕННОГО МАТЧА
                        if removed_keys:
                            logger.info(f"🎯 Отправляем {len(removed_keys)} отдельных сообщений об отмененных матчах")
                            for key in removed_keys:
                                match_data = last_matches_dict[key]
                                message_text = f"➖ <b>Матч завершен/отменен</b>\n\n🏒 {match_data['title']}\n📅 {match_data['date']}\n\nℹ️ Матч больше не доступен для покупки билетов"
                                
                                for chat_id in list(subscribers):
                                    try:
                                        await bot.send_message(chat_id, message_text)
                                        logger.info(f"📤 Отправлено отдельное сообщение об отмене: {match_data['title']}")
                                        await asyncio.sleep(0.3)
                                    except Exception as e:
                                        logger.error(f"❌ Не удалось отправить сообщение {chat_id}: {e}")
                                        subscribers.discard(chat_id)
                            
                            logger.info(f"📊 Уведомления о {len(removed_keys)} завершенных матчах отправлены")

                    # ОБНОВЛЯЕМ КЭШ
                    last_matches_dict = current_dict
                    
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
    time.sleep(30)
    
    while True:
        try:
            response = requests.get(f"{RENDER_URL}/version", timeout=10)
            if response.status_code == 200:
                logger.info(f"🫀 Keep-alive request sent - {response.text}")
            else:
                logger.warning(f"🫀 Keep-alive got status: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Keep-alive failed: {e}")
        
        time.sleep(840)

def run_flask():
    port = int(os.getenv("PORT", 10000))
    logger.info(f"🌐 Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port)

async def main():
    try:
        # ИНИЦИАЛИЗИРУЕМ ПЕРВЫЙ КЭШ
        initial_matches = fetch_matches()
        global last_matches_dict
        last_matches_dict = {f"{m['title']}|{m['date']}": m for m in initial_matches}
        logger.info(f"🎯 Инициализирован кэш с {len(last_matches_dict)} матчами")

        keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
        keep_alive_thread.start()
        logger.info("✅ Keep-alive thread started")

        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("🌐 Webhook удалён, включен polling режим.")

        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        logger.info("✅ Flask server started")

        asyncio.create_task(monitor_matches())
        logger.info("✅ Match monitoring started")

        logger.info("✅ Start polling")
        await dp.start_polling(bot)

    except Exception as e:
        logger.error(f"❌ Fatal error in main: {e}")
        raise

if __name__ == "__main__":
    logger.info("🚀 Starting Hockey Monitor Bot...")
    asyncio.run(main())
