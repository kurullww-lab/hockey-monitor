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
import json
import time

# === Конфигурация ===
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
URL = "https://hcdinamo.by/tickets/"
APP_URL = "https://hockey-monitor.onrender.com/"

# === Логгирование ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# === Flask ===
app = Flask(__name__)

@app.route('/')
def index():
    return jsonify({"status": "ok", "service": "hockey-monitor"})

@app.route('/version')
def version():
    return jsonify({"version": "2.5.0 - TICKET_TRACKING"})

@app.route('/subscribers')
def get_subscribers():
    try:
        subs = load_subscribers()
        return jsonify({"subscribers": list(subs)})
    except Exception as e:
        logging.error(f"Ошибка получения подписчиков: {e}")
        return jsonify({"error": str(e)}), 500

# === Telegram bot ===
session = AiohttpSession()
bot = Bot(
    token=BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# === Память ===
subscribers_file = "subscribers.txt"
last_matches = []
last_message_time = {}  # Для предотвращения дублирования

# Словарь для месяцев
MONTHS = {
    "янв": "января",
    "фев": "февраля",
    "мар": "марта",
    "апр": "апреля",
    "май": "мая",
    "июн": "июня",
    "июл": "июля",
    "авг": "августа",
    "сен": "сентября",
    "окт": "октября",
    "ноя": "ноября",
    "дек": "декабря"
}

# Словарь для дней недели
WEEKDAYS = {
    "пн": "Понедельник",
    "вт": "Вторник",
    "ср": "Среда",
    "чт": "Четверг",
    "пт": "Пятница",
    "сб": "Суббота",
    "вс": "Воскресенье"
}

# === Управление подписчиками ===
def load_subscribers():
    if not os.path.exists(subscribers_file):
        return set()
    try:
        with open(subscribers_file, "r") as f:
            return set(f.read().splitlines())
    except Exception as e:
        logging.error(f"Ошибка загрузки подписчиков: {e}")
        return set()

def save_subscriber(user_id):
    subs = load_subscribers()
    subs.add(str(user_id))
    try:
        with open(subscribers_file, "w") as f:
            f.write("\n".join(subs))
        logging.info(f"Сохранён подписчик: {user_id}")
    except Exception as e:
        logging.error(f"Ошибка сохранения подписчика {user_id}: {e}")

# === Парсинг матчей ===
async def fetch_matches():
    retries = 5
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(URL, timeout=20) as resp:
                    if resp.status != 200:
                        logging.warning(f"⚠️ Ошибка загрузки ({resp.status}) для URL: {URL}, попытка {attempt + 1}")
                        continue
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

                month, weekday = "?", "?"
                if month_raw != "?":
                    match = re.match(r'^([а-я]{3,4})(?:,\s*([а-я]{2}))?$', month_raw, re.IGNORECASE)
                    if match:
                        month = match.group(1)
                        weekday = match.group(2) if match.group(2) else "?"
                    else:
                        month = month_raw

                full_month = MONTHS.get(month, month)
                full_weekday = WEEKDAYS.get(weekday, weekday) if weekday != "?" else ""

                date_formatted = f"{day} {full_month}" if day != "?" and month != "?" else "Дата неизвестна"
                if full_weekday:
                    date_formatted += f", {full_weekday}"

                # Создаем уникальный идентификатор матча
                match_id = f"{date_formatted}|{title}|{time_}"

                # Сохраняем данные матча
                match_data = {
                    "id": match_id,
                    "date": date_formatted,
                    "title": title,
                    "time": time_,
                    "ticket_url": ticket_url,
                    "has_ticket": ticket_url is not None
                }
                matches.append(match_data)
            
            logging.info(f"Возвращено матчей из fetch_matches: {len(matches)}")
            return matches
        except aiohttp.ClientError as e:
            logging.error(f"Ошибка сети на попытке {attempt + 1}/{retries}: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(5)
        except Exception as e:
            logging.error(f"Неожиданная ошибка при парсинге: {e}")
    logging.warning("Все попытки исчерпаны, возвращаем кэш")
    return last_matches

# === Форматирование сообщений ===
def format_match_message(match, include_ticket=True):
    msg = (
        f"📅 {match['date']}\n"
        f"🏒 {match['title']}\n"
        f"🕒 {match['time']}\n"
    )
    if include_ticket and match['ticket_url']:
        msg += f"🎟 <a href='{match['ticket_url']}'>Купить билет</a>"
    elif not include_ticket:
        msg += f"❌ Матч начался или отменён"
    return msg

# === Проверка обновлений ===
async def monitor_matches():
    global last_matches
    await asyncio.sleep(5)
    logging.info("🏁 Мониторинг матчей запущен!")
    while True:
        try:
            current_matches = await fetch_matches()
            
            if last_matches:
                # Создаем словари для быстрого поиска
                current_dict = {match["id"]: match for match in current_matches}
                last_dict = {match["id"]: match for match in last_matches}
                
                current_ids = set(current_dict.keys())
                last_ids = set(last_dict.keys())
                
                added_ids = current_ids - last_ids
                removed_ids = last_ids - current_ids
                common_ids = current_ids & last_ids
                
                # Отслеживаем появление новых матчей
                if added_ids:
                    for match_id in added_ids:
                        match = current_dict[match_id]
                        if match['has_ticket']:
                            message = f"🎉 ПОЯВИЛСЯ НОВЫЙ МАТЧ С БИЛЕТАМИ!\n\n{format_match_message(match)}"
                        else:
                            message = f"🎉 ПОЯВИЛСЯ НОВЫЙ МАТЧ!\n\n{format_match_message(match, include_ticket=False)}\n\nБилеты пока не в продаже"
                        await notify_all([message])
                        logging.info(f"✅ Добавлен матч: {match['title']} (билеты: {match['has_ticket']})")
                
                # Отслеживаем удаление матчей
                if removed_ids:
                    for match_id in removed_ids:
                        match = last_dict[match_id]
                        message = f"⏰ МАТЧ НАЧАЛСЯ!\n\n{format_match_message(match, include_ticket=False)}\n\nУдачи нашей команде! 🏒"
                        await notify_all([message])
                        logging.info(f"⏰ Матч начался: {match['title']}")
                
                # Отслеживаем появление билетов у существующих матчей
                ticket_updates = []
                for match_id in common_ids:
                    current_match = current_dict[match_id]
                    last_match = last_dict[match_id]
                    
                    # Если билеты появились (были None, стали есть URL)
                    if not last_match['has_ticket'] and current_match['has_ticket']:
                        ticket_updates.append(current_match)
                        logging.info(f"🎫 Появились билеты для матча: {current_match['title']}")
                
                # Отправляем уведомления о появлении билетов
                if ticket_updates:
                    for match in ticket_updates:
                        message = f"🎫 ПОЯВИЛИСЬ БИЛЕТЫ НА МАТЧ!\n\n{format_match_message(match)}\n\nУспейте купить! 🏒"
                        await notify_all([message])
                        logging.info(f"🎫 Отправлено уведомление о билетах для: {match['title']}")
                
                if added_ids or removed_ids or ticket_updates:
                    last_matches = current_matches
                    logging.info(f"🔔 Изменения: +{len(added_ids)} новых, -{len(removed_ids)} удалённых, 🎫{len(ticket_updates)} с билетами")
                else:
                    logging.info("✅ Изменений нет")
            else:
                # Первый запуск
                last_matches = current_matches
                logging.info("📝 Первоначальная загрузка матчей завершена")
                
        except Exception as e:
            logging.error(f"Ошибка при мониторинге: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

# === Отправка уведомлений ===
async def notify_all(messages, chat_ids=None):
    subscribers = load_subscribers() if chat_ids is None else set(chat_ids)
    if not subscribers:
        logging.info("❕ Нет подписчиков для уведомления")
        return
    for chat_id in subscribers:
        for msg in messages:
            try:
                await bot.send_message(chat_id, msg)
                logging.info(f"Отправлено уведомление пользователю {chat_id}")
            except Exception as e:
                logging.error(f"Ошибка при отправке пользователю {chat_id}: {e}")

# === Команды ===
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    user_id = message.chat.id
    current_time = time.time()
    if user_id in last_message_time and current_time - last_message_time[user_id] < 60:
        logging.info(f"Игнорируем повторный /start для {user_id}")
        return
    last_message_time[user_id] = current_time

    save_subscriber(user_id)
    logging.info(f"📝 Новый подписчик: {user_id}")
    await message.answer("Вы подписаны на уведомления о матчах Динамо Минск! 🏒")
    
    matches = await fetch_matches()
    if matches:
        # Отправляем все матчи по одному сообщению каждый
        for match in matches:
            message = format_match_message(match)
            await message.answer(message)
    else:
        await message.answer("Пока нет доступных матчей.")

@dp.message(Command("stop"))
async def stop_cmd(message: types.Message):
    user_id = message.chat.id
    subscribers = load_subscribers()
    subscribers.discard(str(user_id))
    try:
        with open(subscribers_file, "w") as f:
            f.write("\n".join(subscribers))
        await message.answer("Вы отписались от уведомлений.")
        logging.info(f"❌ Пользователь {user_id} отписался.")
    except Exception as e:
        logging.error(f"Ошибка при отписке {user_id}: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")

@dp.message(Command("status"))
async def status_cmd(message: types.Message):
    last_check = time.strftime("%Y-%m-%d %H:%M:%S")
    matches_with_tickets = sum(1 for match in last_matches if match['has_ticket']) if last_matches else 0
    status_msg = (
        f"🛠 Статус бота:\n"
        f"👥 Подписчиков: {len(load_subscribers())}\n"
        f"🏒 Всего матчей: {len(last_matches)}\n"
        f"🎫 С билетами: {matches_with_tickets}\n"
        f"⏰ Последняя проверка: {last_check}\n"
        f"🔄 Интервал проверки: {CHECK_INTERVAL} сек"
    )
    await message.answer(status_msg)

# === Самопинг ===
async def keep_awake():
    current_interval = 840  # 14 минут
    min_interval = 300  # 5 минут
    await asyncio.sleep(60)
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(APP_URL, timeout=5) as resp:
                    response_text = await resp.text()
                    if resp.status == 200:
                        logging.info(f"Keep-awake ping: status {resp.status}")
                        current_interval = 840
                    else:
                        logging.warning(f"Keep-awake неудача: статус {resp.status}")
                        current_interval = max(current_interval - 60, min_interval)
        except Exception as e:
            logging.error(f"Keep-awake error: {e}")
            current_interval = max(current_interval - 60, min_interval)
        await asyncio.sleep(current_interval)

# === Запуск ===
async def run_aiogram():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🌐 Webhook удалён, включен polling режим.")
    asyncio.create_task(monitor_matches())
    asyncio.create_task(keep_awake())
    await dp.start_polling(bot)

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

async def main():
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_flask)
    await run_aiogram()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("⛔ Bot stopped")
