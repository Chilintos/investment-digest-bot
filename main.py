#!/usr/bin/env python3
"""
Главная точка входа: запуск бота или утилит.
Usage:
  python -m main              # запуск бота
  python -m main fetch --days 30  # сбор данных
  python -m main search SBER --period month  # тест поиска
"""
import sys
from pathlib import Path

# Добавляем src в путь
sys.path.insert(0, str(Path(__file__).parent / "src"))


def run_bot():
    from src.bot import main as bot_main
    bot_main()


def run_fetch(args):
    import asyncio
    from src.fetch import fetch_all_channels
    from src.config import FETCH_CFG

    days = getattr(args, "days", 30)
    limit = getattr(args, "limit", FETCH_CFG.get("limit_per_channel", 1000))
    asyncio.run(fetch_all_channels(days, limit))


def run_search(args):
    from src.search import search_messages
    from datetime import datetime
    from pathlib import Path

    # CLI: последние новости первыми (for_bot=False)
    results = search_messages(args.query, args.period, args.max, for_bot=False)
    if not results:
        print("Ничего не найдено.")
        return

    # Вывод в терминал
    for r in results:
        media = " [media]" if r["has_media"] == "yes" else ""
        print(f"[{r['date']}] {r['channel']}{media}")
        print(f"  {r['text']}")
        print(f"  Link: {r['link']}")
        print()

    # Сохранение в Markdown
    reports_dir = Path("Reports")
    reports_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"digest_{args.query}_{args.period}_{timestamp}.md"
    filepath = reports_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# Дайджест по «{args.query}» за {args.period}\n\n")
        f.write(f"_Сгенерировано: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}_\n\n")
        f.write(f"Всего найдено: {len(results)} (показано до {args.max})\n\n")
        f.write("---\n\n")

        for i, r in enumerate(results, 1):
            media = " 🖼" if r["has_media"] == "yes" else ""
            f.write(f"## {i}. [{r['date']}] {r['channel']}{media}\n\n")
            f.write(f"{r['text']}\n\n")
            f.write(f"[Открыть в Telegram]({r['link']})\n\n")
            f.write("---\n\n")

    print(f"📄 Сохранено: {filepath}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="investment-digest")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # bot
    sub.add_parser("bot", help="Запустить Telegram-бота")

    # fetch
    p_fetch = sub.add_parser("fetch", help="Собрать посты из каналов")
    p_fetch.add_argument("--days", type=int, default=30, help="Период в днях")
    p_fetch.add_argument("--limit", type=int, default=1000, help="Лимит на канал")

    # search
    p_search = sub.add_parser("search", help="Тестовый поиск по собранным данным")
    p_search.add_argument("query", help="Тикер/название")
    p_search.add_argument("--period", default="month", help="Период")
    p_search.add_argument("--max", type=int, default=20, help="Макс. результатов")

    args = parser.parse_args()

    if args.cmd == "bot":
        run_bot()
    elif args.cmd == "fetch":
        run_fetch(args)
    elif args.cmd == "search":
        run_search(args)