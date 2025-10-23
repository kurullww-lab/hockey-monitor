import asyncio
import logging
import os
import json
import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from flask import Flask

# --------------------------------------------------
# 🔧 Настройки
# --------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
TICKETS_URL = "https://dinamo-minsk.by/tickets/"

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
app = Flask(__name__)

# Файл для хранения данных
MATCHES_FILE = "matches.json"
SUBSCRIBERS_FILE = "subscribers.json"

# --------------------------------------------------
# 📋 Логирование
# --------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# --------------------------------------------------
# 🗂️ Хранилище
# --------------------------------------------------
def load_json(filename):
    if not os.path.exists(filename):
        return []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

matches_old = load_json(MATCHES_FILE)
subscribers = load_json(SUBSCRIBERS_FILE)

# --------------------------------------------------
# 🌍 Загрузка матчей
# --------------------------------------------------
async def fetch_matches():
    async with aiohttp.ClientSession() as session:
        async with session.get(TICKETS_URL) as response:
            html = await response.text()

    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("a.match-item")
    logging.info(f"🎯 Найдено элементов a.match-item: {len(items)}")

    matches = []
    for item in items:
        date = item.select_one(".match-item__date")
        teams = item.select_one(".match-item__teams")
        if not date or not teams:
            continue
        title = teams.text.strip().replace("\n", " ")
        when = date.text.strip()
        link = item.get("href")
        if link and not link.startswith("http"):
            link = f"https://dinamo-minsk.by{link}"
        matches.append({"when": when, "title": title, "url": link})

    logging.info(f"🎯 Найдено матчей: {len(matches)}")
    return matches

# --------------------------------------------------
# 📢 Рассылка сообщений
# --------------------------------------------------
async def notify_all(message: str):
    if not subscribers:
        logging.info("❕ Нет подписчиков для уведомления")
        return

    success, failed = 0, 0
    for user_id in subscribers:
        try:
            await bot.send_message(user_id, message, disable_web_page_preview=True)
            success += 1
        except Exception as e:
            logging.warning(f"⚠️ Не удалось отправить {user_id}: {e}")
            failed += 1
    logging.info(f"📊 Итог отправки: ✅ {success} / ❌ {failed}")

# --------------------------------------------------
# 🔍 Мониторинг матчей
# --------------------------------------------------
async def monitor():
    global matches_old

    while True:
        try:
            logging.info(f"🔄 Проверка...")
            matches_new = await fetch_matches()

            # Первичная загрузка
            if not matches_old:
                matches_old = matches_new
                save_json(MATCHES_FILE, matches_new)
                await notify_all("🏒 Мониторинг запущен!\n\n📅 Найдено матчей: "
                                 f"{len(matches_new)}")
            else:
                old_titles = {m["title"] for m in matches_old}
                new_titles = {m["title"] for m in matches_new}

                added = [m for m in matches_new if m["title"] not in old_titles]
                removed = [m for m in matches_old if m["title"] not in new_titles]

                if added or removed:
                    msg = "🎫 Изменения в расписании матчей:\n"
                    if added:
                        msg += "\n➕ Добавлены:\n" + "\n".join(
                            [f"• {m['when']} — {m['title']} [Купить билеты]({m['url']})" for m in added])
                    if removed:
                        msg += "\n\n➖ Удалены:\n" + "\n".join(
                            [f"• {m['when']} — {m['title']}" for m in removed])
                    await notify_all(msg)
                    matches_old = matches_new
                    save_json(MATCHES_FILE, matches_new)
                    logging.info("✅ Изменения отправлены подписчикам.")
                else:
                    logging.info("✅ Изменений нет")

        except Exception as e:
            logging.error(f"❌ Ошибка мониторинга: {e}")

        logging.info(f"⏰ Следующая проверка через {CHECK_INTERVAL // 60} мин.")
        await asyncio.sleep(CHECK_INTERVAL)

# --------------------------------------------------
# 🤖 Telegram команды
# --------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if user_id not in subscribers:
        subscribers.append(user_id)
        save_json(SUBSCRIBERS_FILE, subscribers)
        await message.answer("✅ Вы подписаны на уведомления о матчах Динамо Минск!")
    else:
        await message.answer("ℹ️ Вы уже подписаны.")

    # Отправляем актуальное расписание
    if matches_old:
        msg = "📅 Текущие матчи:\n\n" + "\n".join(
            [f"{m['when']} — {m['title']} [Билеты]({m['url']})" for m in matches_old]
        )
        await message.answer(msg, disable_web_page_preview=True)
    else:
        await message.answer("Пока нет доступных матчей.")

@dp.message(Command("stop"))
async def cmd_stop(message: types.Message):
    user_id = message.from_user.id
    if user_id in subscribers:
        subscribers.remove(user_id)
        save_json(SUBSCRIBERS_FILE, subscribers)
        await message.answer("❌ Вы отписались от уведомлений.")
    else:
        await message.answer("Вы не были подписаны.")

# --------------------------------------------------
# 🌐 Flask для Render
# --------------------------------------------------
@app.route("/")
def index():
    return "✅ Hockey Monitor работает!"

@app.route("/health")
def health():
    return "ok"

# --------------------------------------------------
# 🚀 Запуск
# --------------------------------------------------
async def main():
    # Удаляем активный webhook, если он есть
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🌐 Webhook удалён, включен polling режим.")

    # Запускаем мониторинг матчей параллельно
    asyncio.create_task(monitor())

    # Запускаем Telegram-бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    from threading import Thread

    # Flask в отдельном потоке
    def run_flask():
        port = int(os.getenv("PORT", 10000))
        logging.info(f"🌐 Запуск веб-сервера на порту {port}...")
        app.run(host="0.0.0.0", port=port)

    Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
