import asyncio
import logging
import json
import requests
import sqlite3
import os
from bs4 import BeautifulSoup
from datetime import datetime
from playwright.async_api import async_playwright
from flask import Flask
import threading
import time

# Конфигурация
URL = "https://hcdinamo.by/tickets/"
BOT_TOKEN = "8416784515:AAG1yGWcgm9gGFPJLodfLvEJrtmIFVJjsu8"
STATE_FILE = "matches_state.json"
CHECK_INTERVAL = 300
ADMIN_ID = "645388044"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Flask веб-сервер
app = Flask(__name__)

@app.route('/')
def home():
    return "🏒 Hockey Monitor Bot is running!"

@app.route('/health')
def health():
    return {"status": "running", "service": "hockey-monitor"}

@app.route('/ping')
def ping():
    return "pong"

def run_web_server():
    """Запускает веб-сервер и ждет пока он забиндится"""
    logging.info("🌐 Запуск веб-сервера на порту 5000...")
    
    # Явно указываем порт и хост
    from waitress import serve
    serve(app, host='0.0.0.0', port=5000)
    
    # Или используем стандартный Flask (менее надежно)
    # app.run(host='0.0.0.0', port=5000, debug=False)

# ========== ОСНОВНЫЕ ФУНКЦИИ БОТА ==========

def init_db():
    conn = sqlite3.connect('subscribers.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS subscribers (chat_id TEXT PRIMARY KEY, username TEXT)''')
    conn.commit()
    conn.close()

def load_subscribers():
    try:
        conn = sqlite3.connect('subscribers.db')
        c = conn.cursor()
        c.execute("SELECT chat_id FROM subscribers")
        subscribers = [row[0] for row in c.fetchall()]
        conn.close()
        return subscribers
    except:
        return []

async def send_telegram(text: str):
    subscribers = load_subscribers()
    for chat_id in subscribers:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
            requests.post(url, json=data, timeout=10)
        except:
            pass

async def fetch_matches():
    """Пробуем оба способа парсинга"""
    # Сначала пробуем простой requests
    matches = await fetch_with_requests()
    if matches:
        return matches
    
    # Если не получилось, пробуем Playwright
    return await fetch_with_playwright()

async def fetch_with_requests():
    """Попробуем простой HTTP запрос без браузера"""
    try:
        logging.info("🌍 Попытка загрузки через requests...")
        response = requests.get(URL, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        matches = []
        for item in soup.select("a.match-item"):
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
        logging.error(f"❌ Ошибка requests: {e}")
        return []

async def fetch_with_playwright():
    """Парсинг через Playwright"""
    for attempt in range(2):
        try:
            logging.info(f"🌍 Загрузка Playwright (попытка {attempt + 1}/2)...")
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
                )
                page = await browser.new_page()
                
                # Используем domcontentloaded вместо networkidle
                await page.goto(URL, timeout=30000, wait_until="domcontentloaded")
                await page.wait_for_selector("div.match-list", timeout=15000)

                html = await page.content()
                await browser.close()

                # парсинг как обычно
                soup = BeautifulSoup(html, "html.parser")
                matches = []
                for item in soup.select("a.match-item"):
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
            logging.error(f"❌ Ошибка Playwright (попытка {attempt + 1}): {e}")
            await asyncio.sleep(5)
    
    return []  # возвращаем пустой список

async def monitor():
    logging.info("🚀 Запуск мониторинга")
    init_db()
    
    # Проверка подписчиков
    subscribers = load_subscribers()
    logging.info(f"👥 Текущие подписчики: {subscribers}")
    
    # Загружаем предыдущее состояние
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            old_matches = json.load(f)
    except:
        old_matches = []
    
    logging.info(f"📂 Загружено предыдущих матчей: {len(old_matches)}")
    
    while True:
        try:
            new_matches = await fetch_matches()
            if new_matches:
                old_titles = {m["title"] for m in old_matches}
                new_titles = {m["title"] for m in new_matches}
                
                added = new_titles - old_titles
                removed = old_titles - new_titles
                
                if added or removed:
                    logging.info(f"✨ Изменения: +{len(added)}, -{len(removed)}")
                    
                    for m in new_matches:
                        if m["title"] in added:
                            msg = f"🎉 НОВЫЙ МАТЧ!\n\n🏒 {m['title']}\n📅 {m['date']}\n\n🎟 <a href='{m['url']}'>Купить билеты</a>"
                            await send_telegram(msg)
                            await asyncio.sleep(1)
                    
                    try:
                        with open(STATE_FILE, "w", encoding="utf-8") as f:
                            json.dump(new_matches, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        logging.error(f"❌ Ошибка сохранения: {e}")
                    
                    old_matches = new_matches
                else:
                    logging.info("✅ Изменений нет")
            
            await asyncio.sleep(CHECK_INTERVAL)
        except Exception as e:
            logging.error(f"Ошибка в цикле: {e}")
            await asyncio.sleep(60)

def main():
    """Главная функция - запускает и веб-сервер и бота"""
    # Сначала запускаем веб-сервер
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    # Даем время веб-серверу запуститься
    time.sleep(3)
    logging.info("🌐 Веб-сервер запущен на порту 5000")
    
    # Затем запускаем бота
    asyncio.run(monitor())

if __name__ == "__main__":
    main()
