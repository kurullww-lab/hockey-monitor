import os
import asyncio
import logging
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from bs4 import BeautifulSoup
from flask import Flask, jsonify
import re
from datetime import datetime, timedelta
import threading

# === Конфигурация ===
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
URL = "https://hcdinamo.by/tickets/"

# === Логгирование ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# === Flask ===
app = Flask(__name__)

@app.route('/')
def index():
    return jsonify({"status": "ok", "service": "hockey-monitor"})

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@app.route('/version')
def version():
    return jsonify({"version": "2.4.1 - FIXED_DEPLOY"})

# === Telegram bot ===
session = AiohttpSession()
bot = Bot(
    token=BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# === Память ===
subscribers = set()
last_matches = []

# Словари для месяцев и дней недели (остаются без изменений)
MONTHS = {
    "янв": "января", "фев": "февраля", "мар": "марта", "апр": "апреля",
    "май": "мая", "июн": "июня", "июл": "июля", "авг": "августа",
    "сен": "сентября", "окт": "октября", "ноя": "ноября", "дек": "декабря"
}

WEEKDAYS = {
    "пн": "Понедельник", "вт": "Вторник", "ср": "Среда", "чт": "Четверг",
    "пт": "Пятница", "сб": "Суббота", "вс": "Воскресенье"
}

# === Парсинг матчей (упрощенная версия для деплоя) ===
async def fetch_matches():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                html = await resp.text()

        soup = BeautifulSoup(html, 'html.parser')
        match_items = soup.select("a.match-item")
        logging.info(f"🎯 Найдено матчей: {len(match_items)}")

        matches = []
        for item in match_items:
            day_elem = item.select_one(".match-day")
            month_elem = item.select_one(".match-month")
            time_elem = item.select_one(".match-times")
            title_elem = item.select_one(".match-title")
            ticket = item.select_one(".btn.tickets-w_t")
            ticket_url = ticket.get("data-w_t") if ticket else None

            day = day_elem.get_text(strip=True) if day_elem else "?"
            month_raw = month_elem.get_text(strip=True).lower() if month_elem else "?"
            time_ = time_elem.get_text(strip=True) if time_elem else "?"
            title = title_elem.get_text(strip=True) if title_elem else "?"

            # Упрощенная обработка даты
            month, weekday = "?", "?"
            if month_raw != "?":
                match = re.match(r'^([а-я]{3,4})(?:,\s*([а-я]{2}))?$', month_raw)
                if match:
                    month = match.group(1)
                    weekday = match.group(2) if match.group(2) else "?"

            full_month = MONTHS.get(month, month)
            full_weekday = WEEKDAYS.get(weekday, weekday) if weekday != "?" else ""

            date_formatted = f"{day} {full_month}" if day != "?" and month != "?" else "Дата неизвестна"
            if full_weekday:
                date_formatted += f", {full_weekday}"

            # Создаем уникальный идентификатор матча
            match_id = f"{date_formatted}|{title}|{time_}"
            
            msg = (
                f"📅 {date_formatted}\n"
                f"🏒 {title}\n"
                f"🕒 {time_}\n"
            )
            if ticket_url:
                msg += f"🎟 <a href='{ticket_url}'>Купить билет</a>"
            
            matches.append({
                "id": match_id,
                "message": msg,
                "date": date_formatted,
                "title": title,
                "time": time_
            })
        return matches
    except Exception as e:
        logging.error(f"❌ Ошибка при парсинге матчей: {e}")
        return []

# === Сравнение матчей ===
def compare_matches(old_matches, new_matches):
    if not old_matches:
        return new_matches, []
    
    old_ids = {match["id"] for match in old_matches}
    new_ids = {match["id"] for match in new_matches}
    
    added_ids = new_ids - old_ids
    removed_ids = old_ids - new_ids
    
    added_matches = [match for match in new_matches if match["id"] in added_ids]
    removed_matches = [match for match in old_matches if match["id"] in removed_ids]
    
    return added_matches, removed_matches

# === Упрощенная проверка начала матча ===
def is_match_started(match):
    try:
        # Базовая проверка - если матч удален, считаем что он начался
        # В реальной реализации здесь должна быть логика проверки времени
        return True  # Упрощенно - всегда считаем что матч начался
    except Exception:
        return True

# === Проверка обновлений ===
async def monitor_matches():
    global last_matches
    await asyncio.sleep(10)  # Даем больше времени на старт
    while True:
        try:
            current_matches = await fetch_matches()
            
            if last_matches:
                added, removed = compare_matches(last_matches, current_matches)
                
                if added:
                    for match in added:
                        await notify_all(f"🎉 ПОЯВИЛСЯ НОВЫЙ МАТЧ!\n\n{match['message']}")
                        logging.info(f"✅ Добавлен матч: {match['title']}")
                
                if removed:
                    for match in removed:
                        await notify_all(f"⏰ МАТЧ НАЧАЛСЯ!\n\n{match['message']}\n\nМатч начался, удачи нашей команде! 🏒")
                        logging.info(f"⏰ Матч начался: {match['title']}")
                
                if added or removed:
                    last_matches = current_matches
                else:
                    logging.info("✅ Изменений нет")
            else:
                # Первый запуск
                last_matches = current_matches
                logging.info("📝 Первоначальная загрузка матчей завершена")
                
        except Exception as e:
            logging.error(f"❌ Ошибка при мониторинге: {e}")
        
        await asyncio.sleep(CHECK_INTERVAL)

# === Отправка уведомлений ===
async def notify_all(message):
    if not subscribers:
        logging.info("❕ Нет подписчиков для уведомления")
        return
    
    for chat_id in list(subscribers):  # Копируем список для безопасности
        try:
            await bot.send_message(chat_id, message)
        except Exception as e:
            logging.error(f"❌ Ошибка при отправке пользователю {chat_id}: {e}")
            # Удаляем невалидного подписчика
            subscribers.discard(chat_id)

# === Команды бота ===
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    subscribers.add(message.chat.id)
    logging.info(f"📝 Новый подписчик: {message.chat.id}")
    await message.answer("Вы подписаны на уведомления о матчах Динамо Минск! 🏒")
    
    if last_matches:
        await message.answer(f"📋 Сейчас отслеживается {len(last_matches)} матчей:")
        for match in last_matches[:3]:  # Отправляем только первые 3 чтобы не спамить
            await message.answer(match["message"])
        if len(last_matches) > 3:
            await message.answer(f"... и еще {len(last_matches) - 3} матчей")
    else:
        await message.answer("Пока нет доступных матчей. Я сообщу, когда появятся новые!")

@dp.message(Command("stop"))
async def stop_cmd(message: types.Message):
    subscribers.discard(message.chat.id)
    await message.answer("Вы отписались от уведомлений.")
    logging.info(f"❌ Пользователь {message.chat.id} отписался.")

@dp.message(Command("status"))
async def status_cmd(message: types.Message):
    status_msg = (
        f"📊 Статус мониторинга:\n"
        f"• Подписчиков: {len(subscribers)}\n"
        f"• Отслеживается матчей: {len(last_matches) if last_matches else 0}\n"
        f"• Проверка каждые: {CHECK_INTERVAL} сек\n"
        f"• Версия: 2.4.1"
    )
    await message.answer(status_msg)

# === Запуск Flask в отдельном потоке ===
def run_flask():
    app.run(host="0.0.0.0", port=10000, debug=False, use_reloader=False)

# === Основная функция ===
async def main():
    logging.info("🚀 Starting application...")
    
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logging.info("🌐 Flask server started in background thread")
    
    # Запускаем мониторинг матчей
    asyncio.create_task(monitor_matches())
    logging.info("🔍 Match monitoring started")
    
    # Запускаем бота
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🤖 Bot starting in polling mode...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    # Проверяем обязательные переменные окружения
    if not BOT_TOKEN:
        logging.error("❌ TELEGRAM_TOKEN environment variable is required!")
        exit(1)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("👋 Application stopped by user")
    except Exception as e:
        logging.error(f"💥 Critical error: {e}")
