import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from flask import Flask, request
import threading
import requests
from bs4 import BeautifulSoup
import json
import time

# === Настройка логов ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# === Переменные окружения ===
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))  # каждые 5 минут

if not BOT_TOKEN:
    raise ValueError("❌ Ошибка: не найден TELEGRAM_TOKEN в переменных окружения!")

# === Инициализация Telegram-бота ===
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# === Flask (для Render webhook) ===
app = Flask(__name__)

# === Данные ===
URL = "https://hcdinamo.by/tickets/"
SUBSCRIBERS_FILE = "subscribers.json"
LAST_MATCHES_FILE = "matches.json"


# === Вспомогательные функции ===
def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_subscribers():
    return load_json(SUBSCRIBERS_FILE, [])


def save_subscribers(subs):
    save_json(SUBSCRIBERS_FILE, subs)


def load_last_matches():
    return load_json(LAST_MATCHES_FILE, [])


def save_last_matches(matches):
    save_json(LAST_MATCHES_FILE, matches)


# === Парсинг матчей ===
def fetch_matches():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(URL, headers=headers, timeout=15)
        logging.info(f"📄 Статус: {resp.status_code}, длина HTML: {len(resp.text)} символов")

        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select("a.match-item")
        logging.info(f"🎯 Найдено элементов a.match-item: {len(items)}")

        matches = []
        for item in items:
            title_elem = item.select_one(".match-title")
            day_elem = item.select_one(".match-day")
            month_elem = item.select_one(".match-month")
            time_elem = item.select_one(".match-times")
            ticket_btn = item.select_one(".btn.tickets-w_t")

            title = title_elem.get_text(strip=True) if title_elem else "Неизвестно"
            day = day_elem.get_text(strip=True) if day_elem else ""
            month = month_elem.get_text(strip=True) if month_elem else ""
            time_ = time_elem.get_text(strip=True) if time_elem else ""
            ticket_url = ticket_btn.get("data-w_t") if ticket_btn else None

            matches.append({
                "title": title,
                "date": f"{day} {month} {time_}",
                "url": ticket_url
            })

        # удаляем дубликаты
        unique = [dict(t) for t in {tuple(sorted(m.items())) for m in matches}]
        logging.info(f"🎯 Уникальных матчей: {len(unique)}")
        return unique

    except Exception as e:
        logging.error(f"Ошибка при загрузке матчей: {e}")
        return []


# === Отправка матчей подписчику ===
async def send_matches(chat_id, matches):
    if not matches:
        await bot.send_message(chat_id, "На данный момент нет доступных матчей.")
        return

    for m in matches:
        text = (
            f"📅 <b>{m['date']}</b>\n"
            f"🏒 {m['title']}\n"
        )
        if m["url"]:
            text += f"🎟 <a href='{m['url']}'>Купить билет</a>"
        await bot.send_message(chat_id, text)


# === /start ===
@dp.message(F.text == "/start")
async def start_handler(message: types.Message):
    subscribers = load_subscribers()
    chat_id = message.chat.id

    if chat_id not in subscribers:
        subscribers.append(chat_id)
        save_subscribers(subscribers)
        logging.info(f"📝 Новый подписчик: {chat_id}")

    await message.answer("Вы подписаны на уведомления о матчах Динамо Минск! ⚡")
    matches = fetch_matches()
    await send_matches(chat_id, matches)


# === /stop ===
@dp.message(F.text == "/stop")
async def stop_handler(message: types.Message):
    subscribers = load_subscribers()
    chat_id = message.chat.id
    if chat_id in subscribers:
        subscribers.remove(chat_id)
        save_subscribers(subscribers)
        await message.answer("Вы отписались от уведомлений.")
    else:
        await message.answer("Вы не были подписаны.")


# === Мониторинг изменений ===
async def monitor_matches():
    logging.info("🏁 Мониторинг матчей запущен!")
    while True:
        try:
            new_matches = fetch_matches()
            old_matches = load_last_matches()

            added = [m for m in new_matches if m not in old_matches]
            removed = [m for m in old_matches if m not in new_matches]

            if added or removed:
                logging.info(f"⚡ Обновления: добавлено {len(added)}, удалено {len(removed)}")
                subs = load_subscribers()
                for chat_id in subs:
                    for m in added:
                        text = (
                            f"🆕 Новый матч!\n"
                            f"📅 <b>{m['date']}</b>\n"
                            f"🏒 {m['title']}\n"
                        )
                        if m["url"]:
                            text += f"🎟 <a href='{m['url']}'>Купить билет</a>"
                        await bot.send_message(chat_id, text)

                    for m in removed:
                        text = f"❌ Матч удалён (возможно, начался):\n<b>{m['title']}</b> — {m['date']}"
                        await bot.send_message(chat_id, text)

                save_last_matches(new_matches)
            else:
                logging.info("✅ Изменений нет")

        except Exception as e:
            logging.error(f"Ошибка в мониторинге: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


# === Flask webhook ===
@app.route("/webhook", methods=["POST"])
async def webhook():
    try:
        update = types.Update.model_validate(await request.get_json())
        await dp.feed_webhook_update(bot, update)
        return "OK", 200
    except Exception as e:
        logging.error(f"Ошибка в webhook: {e}")
        return "Error", 500


@app.route("/")
def index():
    return "OK", 200


# === Запуск ===
def start_monitoring():
    asyncio.run(monitor_matches())


if __name__ == "__main__":
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME', 'hockey-monitor.onrender.com')}/webhook"
    asyncio.run(bot.set_webhook(webhook_url))
    logging.info(f"🌍 Webhook установлен: {webhook_url}")

    threading.Thread(target=start_monitoring, daemon=True).start()

    app.run(host="0.0.0.0", port=10000)
