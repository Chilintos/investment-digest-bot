"""
Сбор сообщений из Telegram-каналов через Telethon (MTProto userbot).
Аналог VBA: подключение к внешнему API, итерация по коллекции, запись в CSV.
"""
import asyncio
import csv
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChannelPrivateError
from telethon.tl.types import Channel, Message

from src.config import API_ID, API_HASH, CHANNELS, FETCH_CFG, PATHS

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def ensure_data_dir() -> Path:
    """Создаёт папку data, если её нет."""
    data_dir = Path(PATHS.get("data_dir", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def messages_csv_path() -> Path:
    """Путь к CSV-файлу с сообщениями."""
    return Path(PATHS.get("messages_csv", "data/messages.csv"))


def init_csv(csv_path: Path) -> None:
    """Создаёт CSV с заголовками, если файла нет."""
    if not csv_path.exists():
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "channel_id",
                "channel_name",
                "channel_username",
                "message_id",
                "date",
                "text",
                "has_media",
                "views",
                "forwards",
            ])
        log.info("Создан новый CSV: %s", csv_path)


def load_existing_ids(csv_path: Path) -> set[int]:
    """Загружает уже сохранённые message_id для дедупликации."""
    if not csv_path.exists():
        return set()
    ids = set()
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ids.add(int(row["message_id"]))
            except (KeyError, ValueError):
                pass
    return ids


def append_messages(csv_path: Path, rows: list[dict[str, Any]]) -> int:
    """Дописывает строки в CSV. Возвращает количество записанных."""
    if not rows:
        return 0
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writerows(rows)
    return len(rows)


async def fetch_channel_history(
    client: TelegramClient,
    channel_username: str,
    channel_name: str,
    since_date: datetime,
    limit: int,
    existing_ids: set[int],
) -> list[dict[str, Any]]:
    """
    Скачивает историю одного канала за период.
    Возвращает список словарей для CSV.
    """
    rows = []
    try:
        entity = await client.get_entity(channel_username)
        if not isinstance(entity, Channel):
            log.warning("%s — не канал, пропускаю", channel_username)
            return rows

        log.info("Сбор: %s (@%s) с %s", channel_name, channel_username, since_date.date())

        async for msg in client.iter_messages(
            entity,
            offset_date=since_date,
            reverse=True,  # от старых к новым
            limit=limit,
        ):
            if not isinstance(msg, Message):
                continue
            if msg.id in existing_ids:
                continue
            if not msg.text:
                continue  # пропускаем пустые/служебные

            rows.append({
                "channel_id": entity.id,
                "channel_name": channel_name,
                "channel_username": channel_username,
                "message_id": msg.id,
                "date": msg.date.astimezone(timezone.utc).isoformat(),
                "text": msg.text.replace("\n", " ").strip(),
                "has_media": "yes" if msg.media else "no",
                "views": getattr(msg, "views", 0) or 0,
                "forwards": getattr(msg, "forwards", 0) or 0,
            })

        log.info("  → получено %d новых постов", len(rows))

    except ChannelPrivateError:
        log.error("%s (@%s) — приватный или нет доступа", channel_name, channel_username)
    except FloodWaitError as e:
        log.error("FloodWait: нужно подождать %d сек. Попробуй позже.", e.seconds)
    except Exception as e:
        log.exception("Ошибка при сборе %s: %s", channel_username, e)

    return rows


async def fetch_all_channels(days_back: int, limit_per_channel: int) -> int:
    """
    Главная функция сбора: итерируется по всем каналам конфига.
    Возвращает общее количество новых сообщений.
    """
    if API_ID == 0 or not API_HASH:
        raise RuntimeError("TELEGRAM_API_ID / TELEGRAM_API_HASH не заданы в .env")

    csv_path = messages_csv_path()
    ensure_data_dir()
    init_csv(csv_path)

    existing_ids = load_existing_ids(csv_path)
    log.info("Уже в базе: %d сообщений", len(existing_ids))

    since_date = datetime.now(timezone.utc) - timedelta(days=days_back)

    client = TelegramClient("userbot_session", API_ID, API_HASH)

    # Явный ввод телефона — чтобы Telethon не показывал "(or bot token)"
    # Подключаемся и авторизуемся
    phone = input("Введите номер телефона (в формате +79XXXXXXXXX): ").strip()
    await client.start(phone=phone)

    log.info("Userbot авторизован")

    total_new = 0
    for ch in CHANNELS:
        new_rows = await fetch_channel_history(
            client=client,
            channel_username=ch["username"],
            channel_name=ch["name"],
            since_date=since_date,
            limit=limit_per_channel,
            existing_ids=existing_ids,
        )
        if new_rows:
            written = append_messages(csv_path, new_rows)
            total_new += written
            existing_ids.update(r["message_id"] for r in new_rows)
            log.info("  → записано в CSV: %d", written)

        # Небольшая пауза между каналами, чтобы не триггерить FloodWait
        await asyncio.sleep(1)

    await client.disconnect()
    log.info("Готово. Всего новых сообщений: %d", total_new)
    return total_new


# CLI-точка входа
async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Сбор постов из Telegram-каналов")
    parser.add_argument("--days", type=int, default=30, help="Период в днях назад")
    parser.add_argument("--limit", type=int, default=1000, help="Лимит на канал")
    args = parser.parse_args()

    await fetch_all_channels(args.days, args.limit)


if __name__ == "__main__":
    asyncio.run(main())