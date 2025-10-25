import os
import asyncio
import logging
import threading
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from flask import Flask, request
import json

# === Логирование ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# === Конфигурация ===
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))
BASE_URL = "https://hcdinamo.by/tickets/"

if not BOT_TOKEN:
    raise ValueError("❌ Не найден TELEGRAM_TOKEN в переменных окружения!")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
app = Flask(__name__)

# === Файлы для хранения данных ===
SUBSCRIBERS_FILE = "subscribers.json"
MATCHES_FILE = "matches.json"


# === Утилиты ===
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


def load_matches():
    return load_json(MATCHES_FILE, [])


def save_matches(matches):
    save_json(MATCHES_FILE, matches)


# === Парсинг матчей ===
def fetch_matches():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(BASE_URL, headers=headers, timeout=15)
        logging.info(f"📄 Статус: {resp.status_code}, длина HTML: {len(resp.text)}")

        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select("a.match-item")
        logging.info(f"🎯 Найдено матчей: {len(items)}")

        matches = []
        for item in items:
            title = item.select_one(".match-title")
            day = item.select_one(".match-day")
            month = item.select_one(".match-month")
            time_ = item.select_one(".match-times")
            link = item.select_one(".btn.tickets-w_t")

            matches.append({
                "title": title.get_text(strip=True) if title else "Неизвестно",
                "date": f"{day.get_text(strip=True)} {month.get_text(strip=True)} {time_.get_text(strip=True)}" if (day and month and time_) else "",
                "url": link.get("data-w_t") if link else None
            })

        unique = [dict(t) for t in {tuple(sorted(m.items())) for m in matches}]
        return unique
    except Exception as e:
        logging.error(f"Ошибка парсинга: {e}")
        return []


# === Отправка матчей пользователю ===
async def send_matches(chat_id, matches):
    if not matches:
        await bot.send_message(chat_id, "На данный момент нет доступных матчей.")
        return

    for m in matches:
        text = f"📅 <b>{m['date']}</b>\n🏒 {m['title']}\n"
        if m["url"]:
            text += f"🎟 <a href='{m['url']}'>Купить билет</a>"
        await bot.send_message(chat_id, text)


# === Команды ===
@dp.message(F.text == "/start")
async def start_cmd(msg: types.Message):
    subs = load_subscribers()
    if msg.chat.id not in subs:
        subs.append(msg.chat.id)
        save_subscribers(subs)
        logging.info(f"📝 Новый подписчик: {msg.chat.id}")
    await msg.answer("Вы подписаны на уведомления о матчах Динамо Минск! ⚡")
    matches = fetch_matches()
    await send_matches(msg.chat.id, matches)


@dp.message(F.text == "/stop")
async def stop_cmd(msg: types.Message):
    subs = load_subscribers()
    if msg.chat.id in subs:
        subs.remove(msg.chat.id)
        save_subscribers(subs)
        await msg.answer("Вы отписались от уведомлений.")
    else:
        await msg.answer("Вы не были подписаны.")


# === Мониторинг матчей ===
async def monitor_matches():
    logging.info("🔍 Match monitoring started")
    last_matches = load_matches()

    while True:
        try:
            current = fetch_matches()
            added = [m for m in current if m not in last_matches]
            removed = [m for m in last_matches if m not in current]

            if added or removed:
                logging.info(f"⚡ Изменения: добавлено {len(added)}, удалено {len(removed)}")
                subs = load_subscribers()

                for chat_id in subs:
                    for m in added:
                        text = f"🆕 Новый матч!\n📅 <b>{m['date']}</b>\n🏒 {m['title']}\n"
                        if m["url"]:
                            text += f"🎟 <a href='{m['url']}'>Купить билет</a>"
                        await bot.send_message(chat_id, text)

                    for m in removed:
                        await bot.send_message(chat_id, f"❌ Матч удалён: <b>{m['title']}</b> — {m['date']}")

                save_matches(current)
            else:
                logging.info("✅ Изменений нет")

            last_matches = current

        except Exception as e:
            logging.error(f"Ошибка мониторинга: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


# === Flask маршруты ===
@app.route("/webhook", methods=["POST"])
async def webhook():
    try:
        update = types.Update.model_validate(await request.get_json())
        await dp.feed_webhook_update(bot, update)
        return "OK", 200
    except Exception as e:
        logging.error(f"Ошибка webhook: {e}")
        return "Error", 500


@app.route("/")
def index():
    return "OK", 200


# === Запуск приложения ===
def start_monitor():
    asyncio.run(monitor_matches())


if __name__ == "__main__":
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME', 'hockey-monitor.onrender.com')}/webhook"
    asyncio.run(bot.set_webhook(webhook_url))
    logging.info(f"🌍 Webhook установлен: {webhook_url}")

    threading.Thread(target=start_monitor, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
