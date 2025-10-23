async def fetch_matches():
    async with aiohttp.ClientSession() as session:
        async with session.get(URL) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, 'html.parser')
    match_items = soup.select("a.match-item")
    logging.info(f"🎯 Найдено матчей: {len(match_items)}")

    matches = []
    for item in match_items:
        # Извлекаем элементы
        day_elem = item.select_one(".match-day")
        month_elem = item.select_one(".match-month")
        time_elem = item.select_one(".match-times")
        title_elem = item.select_one(".match-title")
        ticket = item.select_one(".btn.tickets-w_t")
        ticket_url = ticket.get("data-w_t") if ticket else None

        # Извлекаем текст, если элементы найдены
        day = day_elem.get_text(strip=True) if day_elem else "?"
        month_raw = month_elem.get_text(strip=True).lower() if month_elem else "?"
        time_ = time_elem.get_text(strip=True) if time_elem else "?"
        title = title_elem.get_text(strip=True) if title_elem else "?"

        # Логируем сырые данные
        logging.info(f"Raw date data: day={day}, month_raw={month_raw}")

        # Разделяем месяц и день недели (например, "ноя, пт" -> "ноя" и "пт")
        month, weekday = "?", "?"
        if month_raw != "?":
            # Проверяем, есть ли запятая и день недели
            match = re.match(r'^([а-я]{3,4})(?:,\s*([а-я]{2}))?$', month_raw)
            if match:
                month = match.group(1)  # Например, "ноя"
                weekday = match.group(2) if match.group(2) else "?"  # Например, "пт" или "?"
            else:
                month = month_raw  # Если нет запятой, считаем, что это только месяц

        # Преобразуем в полные названия
        full_month = MONTHS.get(month, month)  # Если месяц не в словаре, оставляем как есть
        full_weekday = WEEKDAYS.get(weekday, weekday) if weekday != "?" else ""

        # Формируем строку даты
        date_formatted = f"{day} {full_month}" if day != "?" and month != "?" else "Дата неизвестна"
        if full_weekday:
            date_formatted += f", {full_weekday}"

        msg = (
            f"📅 {date_formatted}\n"
            f"🏒 {title}\n"
            f"🕒 {time_}\n"
        )
        if ticket_url:
            msg += f"🎟 <a href='{ticket_url}'>Купить билет</a>"
        matches.append(msg)
    return matches
