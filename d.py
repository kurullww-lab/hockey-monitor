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

# ... (остальной код остается таким же до функции is_match_started)

# === Проверка, начался ли матч ===
def is_match_started(match):
    try:
        # Получаем текущее время
        now = datetime.now()
        
        # Парсим дату и время матча из информации
        match_date_str = match["date"]
        match_time_str = match["time"]
        
        logging.info(f"🔍 Анализируем матч: {match['title']}")
        logging.info(f"📅 Дата матча: {match_date_str}")
        logging.info(f"🕒 Время матча: {match_time_str}")
        
        # Пытаемся определить дату матча
        match_date = parse_match_date(match_date_str, now)
        if not match_date:
            logging.warning(f"❌ Не удалось распарсить дату: {match_date_str}")
            return False
        
        # Пытаемся определить время матча
        match_time = parse_match_time(match_time_str)
        if not match_time:
            logging.warning(f"❌ Не удалось распарсить время: {match_time_str}")
            return False
        
        # Комбинируем дату и время
        match_datetime = datetime.combine(match_date, match_time)
        
        # Проверяем, находится ли матч в "окне начала" (текущее время ± 3 часа от времени матча)
        time_diff = now - match_datetime
        time_diff_hours = time_diff.total_seconds() / 3600
        
        logging.info(f"⏰ Время матча: {match_datetime}")
        logging.info(f"⏰ Текущее время: {now}")
        logging.info(f"📊 Разница: {time_diff_hours:.2f} часов")
        
        # Матч считается начавшимся, если он должен был начаться в последние 3 часа
        # и еще не прошел день с начала
        is_started = -1 <= time_diff_hours <= 24
        
        if is_started:
            logging.info(f"🎯 Матч начался: {match['title']}")
        else:
            logging.info(f"💤 Матч не начался или уже давно прошел: {match['title']}")
            
        return is_started
        
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке начала матча {match['title']}: {e}")
        return False

# === Парсинг даты матча ===
def parse_match_date(date_str, current_date):
    try:
        # Примеры форматов: "15 ноября, Пятница", "15 ноября"
        # Удаляем день недели если есть
        date_clean = re.split(r',', date_str)[0].strip()
        
        # Ищем число и месяц
        match = re.match(r'(\d{1,2})\s+([а-я]+)', date_clean)
        if not match:
            return None
            
        day = int(match.group(1))
        month_name = match.group(2).lower()
        
        # Обратный словарь для месяцев
        MONTHS_REVERSE = {
            "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
            "мая": 5, "июня": 6, "июля": 7, "августа": 8,
            "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12
        }
        
        month = MONTHS_REVERSE.get(month_name)
        if not month:
            return None
        
        # Пробуем текущий год
        year = current_date.year
        match_date = datetime(year, month, day).date()
        
        # Если дата матча в прошлом относительно текущей даты (но в пределах года),
        # возможно матч в следующем году
        if match_date < current_date.date():
            # Проверяем, не слишком ли рано (больше 2 месяцев разницы)
            days_diff = (current_date.date() - match_date).days
            if days_diff > 60:  # Если разница больше 2 месяцев
                match_date = datetime(year + 1, month, day).date()
        
        return match_date
        
    except Exception as e:
        logging.error(f"❌ Ошибка парсинга даты '{date_str}': {e}")
        return None

# === Парсинг времени матча ===
def parse_match_time(time_str):
    try:
        # Примеры форматов: "19:30", "19.30", "19-30"
        # Нормализуем разделитель
        time_normalized = re.sub(r'[\.\-]', ':', time_str).strip()
        
        # Ищем время в формате HH:MM
        match = re.match(r'(\d{1,2}):(\d{2})', time_normalized)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            
            # Проверяем валидность времени
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                return datetime.strptime(f"{hours:02d}:{minutes:02d}", "%H:%M").time()
        
        return None
        
    except Exception as e:
        logging.error(f"❌ Ошибка парсинга времени '{time_str}': {e}")
        return None

# ... (остальной код остается таким же)
