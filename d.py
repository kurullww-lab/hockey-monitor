import asyncio
import logging
import json
import requests
import sqlite3
import os
from bs4 import BeautifulSoup
from datetime import datetime
from playwright.async_api import async_playwright

URL = "https://hcdinamo.by/tickets/"
BOT_TOKEN = "8416784515:AAG1yGWcgm9gGFPJLodfLvEJrtmIFVJjsu8"
STATE_FILE = "matches_state.json"
CHECK_INTERVAL = 300  # 5 минут

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ========== БАЗА ДАННЫХ ДЛЯ ПОДПИСЧИКОВ ==========

def init_db():
    """Инициализация базы данных подписчиков"""
    conn = sqlite3.connect('subscribers.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS subscribers
                 (chat_id TEXT PRIMARY KEY, username TEXT, subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()
    logging.info("✅ База данных подписчиков инициализирована")

def load_subscribers():
    """Загрузка списка подписчиков из базы"""
    try:
        conn = sqlite3.connect('subscribers.db')
        c = conn.cursor()
        c.execute("SELECT chat_id FROM subscribers")
        subscribers = [row[0] for row in c.fetchall()]
        conn.close()
        return subscribers
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки подписчиков: {e}")
        return []

def add_subscriber(chat_id, username=""):
    """Добавление подписчика в базу"""
    try:
        conn = sqlite3.connect('subscribers.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO subscribers (chat_id, username) VALUES (?, ?)", 
                 (chat_id, username))
        conn.commit()
        conn.close()
        logging.info(f"✅ Добавлен подписчик: {chat_id} ({username})")
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка добавления подписчика: {e}")
        return False

def remove_subscriber(chat_id):
    """Удаление подписчика из базы"""
    try:
        conn = sqlite3.connect('subscribers.db')
        c = conn.cursor()
        c.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        logging.info(f"❌ Удален подписчик: {chat_id}")
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка удаления подписчика: {e}")
        return False

# ========== TELEGRAM ФУНКЦИИ ==========

async def send_direct_message(chat_id: str, text: str):
    """Отправляет сообщение конкретному пользователю"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logging.error(f"❌ Ошибка отправки прямого сообщения: {e}")
        return False

async def send_telegram(text: str):
    """Отправка уведомлений всем подписчикам"""
    subscribers = load_subscribers()
    if not subscribers:
        logging.warning("⚠️ Нет подписчиков для отправки уведомлений")
        return False
    
    success_count = 0
    
    for chat_id in subscribers:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            r = requests.post(url, json=data, timeout=10)
            if r.status_code == 200:
                success_count += 1
            else:
                logging.warning(f"⚠️ Ошибка для {chat_id}: {r.status_code}")
                # Если пользователь заблокировал бота, удаляем его
                if r.status_code == 403:
                    remove_subscriber(chat_id)
        except Exception as e:
            logging.error(f"❌ Ошибка отправки для {chat_id}: {e}")
    
    logging.info(f"📨 Отправлено {success_count}/{len(subscribers)} пользователям")
    return success_count > 0

async def check_telegram_updates():
    """Проверяет новые сообщения от пользователей"""
    last_update_id = 0
    
    # Загрузка последнего обработанного update_id
    try:
        if os.path.exists('last_update.txt'):
            with open('last_update.txt', 'r') as f:
                last_update_id = int(f.read().strip())
    except:
        pass
    
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        params = {"offset": last_update_id + 1, "timeout": 5}
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    last_update_id = update["update_id"]
                    
                    if "message" in update and "text" in update["message"]:
                        message = update["message"]
                        chat_id = str(message["chat"]["id"])
                        text = message["text"].strip()
                        username = message["chat"].get("username", "")
                        
                        if text == "/start":
                            if add_subscriber(chat_id, username):
                                welcome_msg = (
                                    "🎉 <b>Вы подписались на уведомления о новых матчах ХК Динамо-Минск!</b>\n\n"
                                    "🏒 <b>Что я делаю:</b>\n"
                                    "• Отслеживаю появление новых матчей на сайте hcdinamo.by\n"
                                    "• Присылаю уведомления о новых играх\n"
                                    "• Сообщаю об изменениях в расписании\n\n"
                                    "🔔 <b>Теперь вы будете получать уведомления!</b>\n\n"
                                    "❌ Чтобы отписаться, отправьте /stop\n"
                                    "ℹ️ Информация о боте - /info"
                                )
                                await send_direct_message(chat_id, welcome_msg)
                            
                        elif text == "/stop":
                            if remove_subscriber(chat_id):
                                goodbye_msg = "❌ <b>Вы отписались от уведомлений.</b>"
                                await send_direct_message(chat_id, goodbye_msg)
                        
                        elif text == "/info":
                            subscribers_count = len(load_subscribers())
                            info_msg = (
                                "🏒 <b>Мониторинг билетов ХК Динамо-Минск</b>\n\n"
                                "📊 <b>Статистика:</b>\n"
                                f"• Подписчиков: {subscribers_count}\n"
                                "• Сайт: hcdinamo.by/tickets/\n"
                                "• Проверка каждые 5 минут\n\n"
                                "🔔 <b>Что отслеживаю:</b>\n"
                                "• Появление новых матчей\n"
                                "• Изменения в расписании\n"
                                "• Удаление матчей\n\n"
                                "⚙️ <b>Команды:</b>\n"
                                "/start - подписаться на уведомления\n"
                                "/stop - отписаться от уведомлений\n"
                                "/info - эта информация\n\n"
                                "📞 <b>Поддержка:</b>\n"
                                "Для вопросов и предложений обращайтесь к @kurullww"
                            )
                            await send_direct_message(chat_id, info_msg)
            
            # Сохраняем последний обработанный update_id
            with open('last_update.txt', 'w') as f:
                f.write(str(last_update_id))
                
    except Exception as e:
        logging.error(f"❌ Ошибка проверки обновлений: {e}")

# ========== ПАРСИНГ И МОНИТОРИНГ ==========

async def fetch_matches():
    """Парсинг через Playwright с защитой от таймаутов"""
    for attempt in range(3):
        try:
            logging.info(f"🌍 Загрузка страницы (попытка {attempt + 1}/3)...")
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
                page = await browser.new_page()
                await page.goto(URL, timeout=45000, wait_until="domcontentloaded")
                await page.wait_for_selector("div.match-list", timeout=20000)

                html = await page.content()
                await browser.close()

            soup = BeautifulSoup(html, "html.parser")
            blocks = soup.select("div.match-list")
            logging.info(f"🔎 Найдено блоков match-list: {len(blocks)}")

            matches = []
            for b in blocks:
                for item in b.select("a.match-item"):
                    title = item.select_one("div.match-title")
                    date = item.select_one("div.match-day")
                    time = item.select_one("div.match-times")
                    if title and date and time:
                        href = item.get("href", URL)
                        if href.startswith("/"):
                            href = "https://hcdinamo.by" + href
                        matches.append({
                            "title": title.text.strip(),
                            "date": f"{date.text.strip()} {time.text.strip()}",
                            "url": href
                        })

            logging.info(f"🎯 Найдено матчей: {len(matches)}")
            return matches

        except Exception as e:
            logging.error(f"❌ Ошибка парсинга: {e}")
            await asyncio.sleep(5)

    logging.error("🚫 Не удалось получить данные после 3 попыток.")
    return []

def load_state():
    """Загрузка предыдущего состояния матчей"""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_state(matches):
    """Сохранение текущего состояния матчей"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(matches, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения состояния: {e}")

# ========== ГЛАВНЫЙ ЦИКЛ ==========

async def monitor():
    """Главный цикл мониторинга"""
    logging.info(f"🚀 Запуск мониторинга Dinamo Tickets")
    logging.info(f"🌐 Сайт: {URL}")
    
    # Инициализация базы данных
    init_db()
    
    # Загрузка текущих подписчиков
    subscribers = load_subscribers()
    logging.info(f"📋 Загружено подписчиков: {len(subscribers)}")

    old_matches = load_state()
    logging.info(f"📂 Загружено предыдущих матчей: {len(old_matches)}")

    while True:
        try:
            # Проверяем новые команды от пользователей
            await check_telegram_updates()
            
            # Основной мониторинг матчей
            new_matches = await fetch_matches()
            if not new_matches:
                logging.warning("⚠️ Не удалось получить матчи, повтор через 1 мин.")
                await asyncio.sleep(60)
                continue

            old_titles = {m["title"] for m in old_matches}
            new_titles = {m["title"] for m in new_matches}

            added = new_titles - old_titles
            removed = old_titles - new_titles

            if added or removed:
                logging.info(f"✨ Изменения: +{len(added)}, -{len(removed)}")

                for m in new_matches:
                    if m["title"] in added:
                        msg = (
                            f"🎉 <b>НОВЫЙ МАТЧ!</b>\n\n"
                            f"🏒 {m['title']}\n"
                            f"📅 {m['date']}\n\n"
                            f"🎟 <a href='{m['url']}'>Купить билеты</a>"
                        )
                        await send_telegram(msg)
                        await asyncio.sleep(1)  # Задержка между отправками

                for m in old_matches:
                    if m["title"] in removed:
                        msg = (
                            f"🗑️ <b>МАТЧ УДАЛЁН</b>\n\n"
                            f"🏒 {m['title']}\n"
                            f"📅 {m['date']}"
                        )
                        await send_telegram(msg)
                        await asyncio.sleep(1)

                save_state(new_matches)
                old_matches = new_matches
            else:
                logging.info("✅ Изменений нет")

            logging.info(f"📊 Всего матчей: {len(new_matches)}")
            await asyncio.sleep(CHECK_INTERVAL)

        except Exception as e:
            logging.error(f"💥 Ошибка в цикле: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(monitor())
