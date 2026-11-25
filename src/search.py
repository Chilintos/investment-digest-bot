"""
Фильтрация и поиск сообщений по тикеру/названию + период.
Аналог VBA: AutoFilter + сортировка + InStr/RegExp для поиска подстроки.
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from src.config import ALIASES, PATHS, PERIODS


def messages_csv_path() -> Path:
    return Path(PATHS.get("messages_csv", "data/messages.csv"))


def load_messages() -> pd.DataFrame:
    """Загружает CSV в DataFrame, парсит даты."""
    csv_path = messages_csv_path()
    if not csv_path.exists():
        return pd.DataFrame(columns=[
            "channel_id", "channel_name", "channel_username",
            "message_id", "date", "text", "has_media", "views", "forwards"
        ])

    df = pd.read_csv(csv_path)
    if df.empty:
        return df

    # Парсим даты в UTC
    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    df = df.dropna(subset=["date"])
    return df


def build_search_terms(query: str) -> list[str]:
    """
    Формирует список терминов для поиска:
    - сам запрос (lowercase)
    - синонимы из aliases.json (если запрос похож на тикер)
    - простая словоформа: добавляем s/es для англ., а/я/ы/и для рус.
    """
    q = query.strip().lower()
    terms = {q}

    # Проверяем aliases — если query совпадает с ключом или значением
    for ticker, synonyms in ALIASES.items():
        if q == ticker.lower() or q in [s.lower() for s in synonyms]:
            terms.add(ticker.lower())
            terms.update(s.lower() for s in synonyms)
            break

    # Простая морфология: добавляем распространённые окончания
    # Английские: s, es
    # Русские: а, я, ы, и, о, е, ым, ом, ем, ах, ях, ами, ями
    extra = set()
    for t in terms:
        # англ. множественное число
        if re.match(r"^[a-z]+$", t):
            extra.add(t + "s")
            if t.endswith(("s", "x", "z", "ch", "sh")):
                extra.add(t + "es")
        # русские падежи (грубая эвристика)
        if re.match(r"^[а-яё]+$", t):
            endings = ["а", "я", "ы", "и", "о", "е", "ым", "ом", "ем", "ах", "ях", "ами", "ями"]
            for end in endings:
                extra.add(t + end)
    terms.update(extra)

    return list(terms)


def filter_by_query(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """
    Фильтрует DataFrame: оставляет строки, где text содержит любой из терминов.
    Поиск case-insensitive, по словам (граница слова).
    """
    if df.empty or not query.strip():
        return df.iloc[0:0]

    terms = build_search_terms(query)
    # Регекс: граница слова или начало/конец строки
    pattern = r"(^|\W)(" + "|".join(re.escape(t) for t in terms) + r")(\W|$)"
    regex = re.compile(pattern, flags=re.IGNORECASE)

    mask = df["text"].apply(lambda x: bool(regex.search(str(x))))
    return df[mask].copy()


def filter_by_period(df: pd.DataFrame, period_key: str) -> pd.DataFrame:
    """Фильтрует по периодам: month/quarter/half_year/year (дни назад)."""
    if df.empty:
        return df

    days = PERIODS.get(period_key)
    if not days:
        # Если передано число — трактуем как дни
        try:
            days = int(period_key)
        except ValueError:
            return df.iloc[0:0]

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return df[df["date"] >= cutoff].copy()


def sort_chronological(df: pd.DataFrame, ascending: bool = True) -> pd.DataFrame:
    """Сортирует по дате: ascending=True — от старых к новым."""
    if df.empty:
        return df
    return df.sort_values("date", ascending=ascending).reset_index(drop=True)


def format_results(df: pd.DataFrame, max_items: int = 50) -> list[dict[str, Any]]:
    """
    Формирует список словарей для выдачи в боте.
    Ограничивает max_items.
    Ожидает, что df уже отсортирован правильно (для бота: ascending=True, старые → новые).
    """
    if df.empty:
        return []

    df = df.head(max_items)
    results = []
    for _, row in df.iterrows():
        dt = row["date"]
        if pd.isna(dt):
            date_str = "неизвестно"
        else:
            date_str = dt.strftime("%d.%m.%Y %H:%M")

        # Полный текст поста (без обрезки)
        text = str(row["text"])

        # Ссылка на сообщение: https://t.me/channel_username/message_id
        link = f"https://t.me/{row['channel_username']}/{row['message_id']}"

        results.append({
            "date": date_str,
            "channel": row["channel_name"],
            "text": text,
            "link": link,
            "has_media": row["has_media"],
        })
    return results


def search_messages(query: str, period_key: str, max_items: int = 50, for_bot: bool = True) -> list[dict[str, Any]]:
    """
    Главная функция: загружает -> фильтрует по запросу -> фильтрует по периоду ->
    сортирует -> форматирует.

    Args:
        for_bot: True — вернуть в хронологическом порядке (старые → новые) для бота
                 False — вернуть последние (новые → старые) для CLI
    """
    df = load_messages()
    df = filter_by_query(df, query)
    df = filter_by_period(df, period_key)

    # Сначала сортируем по убыванию (новые → старые), берём топ-N
    df = sort_chronological(df, ascending=False)
    df = df.head(max_items)

    # Для бота — переворачиваем в хронологическом порядке (старые → новые)
    if for_bot:
        df = sort_chronological(df, ascending=True)

    return format_results(df, max_items)


# CLI для тестов
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Поиск новостей по тикеру/периоду")
    parser.add_argument("query", help="Тикер или название (например, SBER)")
    parser.add_argument("--period", default="month", help="Период: month/quarter/half_year/year или число дней")
    parser.add_argument("--max", type=int, default=20, help="Макс. результатов")
    args = parser.parse_args()

    results = search_messages(args.query, args.period, args.max)
    if not results:
        print("Ничего не найдено.")
    else:
        for r in results:
            print(f"[{r['date']}] {r['channel']}: {r['text'][:100]}... → {r['link']}")