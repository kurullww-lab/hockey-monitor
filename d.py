import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiohttp import web
import aiohttp
from bs4 import BeautifulSoup
import json
import datetime

# === НАСТРОЙКА ЛОГОВ ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ Не найден TELEGRAM_TOKEN в Environment!")

# === НАСТРОЙКА БОТА ===
bot = Bot(token=BOT_TOKEN, default=types.DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# === ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ===
MATCHES_FILE = "matches.json"
SUBSCRIBERS_FILE = "subscribers.json"
CHECK_INTERVAL = 300  # 5 минут

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def load_json(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

async def fetch_matches():
    """Получение списка матчей со страницы"""
    url = "https://hcdinamo.by/local/ajax/tickets_list.php"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://hcdinamo.by/tickets/",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "keep-alive"
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=30) as resp:
                html = await resp.text()
                logging.info(f"📄 Статус загрузки {resp.status}, длина HTML: {len(html)} символов")

                if resp.status != 200:
                    return []

                soup = BeautifulSoup(html, "html.parser")
                matches_html = soup.select("a.match-item")
                logging.info(f"🎯 Найдено элементов a.match-item: {len(matches_html)}")

                matches = []
                for i, match in enumerate(matches_html, 1):
                    date = match.select_one(".match__date")
                    if not date:
                        continue
                    parts = date.text.strip().split()
                    if len(parts) < 4:
                        continue
                    day, month, day_of_week, time = parts[:4]
                    match_text = f"{day} {month} {day_of_week} {time}"
                    home_team = match.select_one(".match__team--home").text.strip()
                    away_team = match.select_one(".match__team--away").text.strip()
                    ticket_link = match.get("href")
                    matches.append({
                        "date": match_text,
                        "teams": f"{home_team} — {away_team}",
                        "ticket_link": f"https://hcdinamo.by{ticket_link}"
                    })
                    logging.info(f"🔍 Матч {i}: {match_text}, {home_team} vs {away_team}")

                logging.info(f"🎯 Найдено матчей: {len(matches)}")
                return matches

        except Exception as e:
            logging.error(f"Ошибка при получении матчей: {e}")
            return []

async def notify_subscribers(message_text):
    subscribers = load_json(SUBSCRIBERS_FILE)
    for user_id in subscribers:
        try:
            await bot.send_message(user_id, message_text)
        except Exception as e:
            logging.warning(f"⚠️ Не удалось отправить сообщение {user_id}: {e}")

# === МОНИТОРИНГ ===

async def monitor_matches():
    logging.info("🏁 Мониторинг матчей запущен!")
    old_matches = load_json(MATCHES_FILE)

    while True:
        new_matches = await fetch_matches()
        if not new_matches:
            logging.info("⚠️ Матчи не найдены, возможно сайт временно недоступен")
            await asyncio.sleep(CHECK_INTERVAL)
            continue

        if new_matches != old_matches:
            logging.info("🔔 Обнаружены изменения в списке матчей!")
            save_json(MATCHES_FILE, new_matches)

            added = [m for m in new_matches if m not in old_matches]
            removed = [m for m in old_matches if m not in new_matches]

            message_parts = []
            if added:
                for match in added:
                    message_parts.append(
                        f"🆕 Новый матч!\n📅 {match['date']}\n🏒 {match['teams']}\n🎟 <a href='{match['ticket_link']}'>Купить билет</a>"
                    )
            if removed:
                for match in removed:
                    message_parts.append(
                        f"⏰ Матч удалён (возможно, уже идёт):\n📅 {match['date']}\n🏒 {match['teams']}"
                    )

            if message_parts:
                await notify_subscribers("\n\n".join(message_parts))

        else:
            logging.info("✅ Изменений нет")

        old_matches = new_matches
        await asyncio.sleep(CHECK_INTERVAL)

# === ОБРАБОТЧИКИ КОМАНД ===

@dp.message(Command("start"))
async def start_command(message: types.Message):
    subscribers = load_json(SUBSCRIBERS_FILE)
    if message.from_user.id not in subscribers:
        subscribers.append(message.from_user.id)
        save_json(SUBSCRIBERS_FILE, subscribers)

    await message.answer(
        "Вы подписаны на уведомления о матчах Динамо Минск!\n\n"
        "Буду сообщать о новых матчах и изменениях расписания 🏒"
    )

    # При первом запуске — показать актуальные матчи
    matches = load_json(MATCHES_FILE)
    if matches:
        for match in matches:
            await message.answer(
                f"📅 {match['date']}\n🏒 {match['teams']}\n🎟 <a href='{match['ticket_link']}'>Купить билет</a>"
            )
    else:
        await message.answer("Пока нет данных о матчах.")

@dp.message(Command("stop"))
async def stop_command(message: types.Message):
    subscribers = load_json(SUBSCRIBERS_FILE)
    if message.from_user.id in subscribers:
        subscribers.remove(message.from_user.id)
        save_json(SUBSCRIBERS_FILE, subscribers)
        await message.answer("Вы отписаны от уведомлений ⚙️")
    else:
        await message.answer("Вы не были подписаны.")

# === WEBHOOK (для Render) ===

async def on_startup(app):
    webhook_url = f"https://hockey-monitor.onrender.com/webhook"
    await bot.set_webhook(webhook_url)
    logging.info(f"🌍 Webhook установлен: {webhook_url}")
    asyncio.create_task(monitor_matches())

async def on_shutdown(app):
    await bot.delete_webhook()
    logging.info("❌ Webhook удалён")

async def handle_webhook(request):
    data = await request.json()
    update = types.Update(**data)
    await dp.feed_update(bot, update)
    return web.Response(text="ok")

async def handle_root(request):
    return web.Response(text="Hockey monitor is running ✅")

# === ЗАПУСК ===

def main():
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    app.router.add_get("/", handle_root)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, port=10000)

if __name__ == "__main__":
    main()
