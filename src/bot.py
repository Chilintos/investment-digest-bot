"""
Telegram-бот для приёма запросов и выдачи дайджеста.
Аналог VBA: UserForm + события кнопок + вызов функций поиска.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Optional, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from src.config import BOT_TOKEN, PERIODS
from src.search import search_messages

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Константы периодов для кнопок
PERIOD_LABELS: Final = {
    "day": "📅 День (1 дн.)",
    "week": "📅 Неделя (7 дн.)",
    "month": "📅 Месяц (30 дн.)",
    "quarter": "📅 Квартал (90 дн.)",
    "half_year": "📅 Полугодие (180 дн.)",
    "year": "📅 Год (365 дн.)",
}

# Кнопки для Reply-клавиатуры (постоянная, снизу экрана)
PERIOD_BUTTONS: Final = [
    ["📅 День", "📅 Неделя"],
    ["📅 Месяц", "📅 Квартал"],
    ["📅 Полугодие", "📅 Год"],
    ["🔄 Новый запрос", "ℹ️ Помощь"],
]

# Состояния диалога (простой словарь в памяти)
user_state: dict[int, dict] = {}


def period_keyboard() -> InlineKeyboardMarkup:
    """Inline-клавиатура выбора периода (для сообщения с результатом)."""
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"period:{key}")]
        for key, label in PERIOD_LABELS.items()
    ]
    return InlineKeyboardMarkup(buttons)


def reply_keyboard() -> ReplyKeyboardMarkup:
    """Постоянная Reply-клавиатура снизу экрана."""
    return ReplyKeyboardMarkup(PERIOD_BUTTONS, resize_keyboard=True, one_time_keyboard=False)


def parse_ticker_period(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Парсит сообщение вида: "SBER month" или "Газпром квартал".
    Возвращает (ticker, period_key) или (None, None).
    """
    text = text.strip()
    parts = text.split()
    if len(parts) < 2:
        return None, None

    # Последнее слово — период
    period_word = parts[-1].lower()
    period_map = {
        "день": "day", "day": "day", "1": "day",
        "неделя": "week", "week": "week", "7": "week",
        "месяц": "month", "month": "month", "30": "month",
        "квартал": "quarter", "quarter": "quarter", "90": "quarter",
        "полугодие": "half_year", "half_year": "half_year", "180": "half_year",
        "год": "year", "year": "year", "365": "year",
    }

    period_key = period_map.get(period_word)
    if not period_key:
        return None, None

    # Всё, кроме последнего слова — тикер
    ticker = " ".join(parts[:-1]).strip()
    return ticker, period_key


# Максимальная длина сообщения в Telegram
MAX_MESSAGE_LENGTH = 4000


def split_long_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Разбивает длинный текст на части, не превышающие max_length."""
    if len(text) <= max_length:
        return [text]

    parts = []
    current = ""

    for line in text.split("\n"):
        # Если добавление строки превысит лимит
        if len(current) + len(line) + 1 > max_length:
            if current:
                parts.append(current)
            current = line
        else:
            if current:
                current += "\n" + line
            else:
                current = line

    if current:
        parts.append(current)

    return parts


def format_digest(results: list[dict], query: str, period_key: str) -> list[str]:
    """Формирует текст сообщения с дайджестом. Возвращает список частей (если длинное)."""
    if not results:
        return [
            f"🔍 По запросу «<b>{query}</b>» за <b>{PERIOD_LABELS.get(period_key, period_key)}</b> ничего не найдено.\n\n"
            "Попробуй:\n"
            "• Другой тикер/название\n"
            "• Больший период\n"
            "• Проверь, собраны ли данные (команда /fetch)"
        ]

    lines = [
        f"📰 <b>Дайджест по «{query}»</b> за <b>{PERIOD_LABELS.get(period_key, period_key)}</b>",
        f"Найдено: <b>{len(results)}</b> сообщений (показано до 50)\n",
        "⚠️ <i>Это сводка по открытым каналам, не финансовый совет. Проверяй факты по первоисточникам.</i>\n",
    ]

    for i, r in enumerate(results, 1):
        media_mark = " 🖼" if r["has_media"] == "yes" else ""
        # Заголовок новости: дата + канал — жирнее, как заголовок
        lines.append(
            f"{i}. <b>{r['date']} | {r['channel']}</b>{media_mark}\n"
            f"{r['text']}\n"
            f"🔗 <a href=\"{r['link']}\">Открыть в Telegram</a>\n"
        )

    full_text = "\n".join(lines)
    return split_long_message(full_text)


def save_digest_to_md(results: list[dict], query: str, period_key: str) -> Path:
    """Сохраняет дайджест в Markdown-файл в папку Reports/."""
    reports_dir = Path("Reports")
    reports_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_query = query.replace("/", "_").replace("\\", "_")
    filename = f"digest_{safe_query}_{period_key}_{timestamp}.md"
    filepath = reports_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# Дайджест по «{query}» за {PERIOD_LABELS.get(period_key, period_key)}\n\n")
        f.write(f"_Сгенерировано: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}_\n\n")
        f.write(f"Всего найдено: {len(results)} (показано до 50)\n\n")
        f.write("---\n\n")

        for i, r in enumerate(results, 1):
            media = " 🖼" if r["has_media"] == "yes" else ""
            f.write(f"## {i}. [{r['date']}] {r['channel']}{media}\n\n")
            f.write(f"{r['text']}\n\n")
            f.write(f"[Открыть в Telegram]({r['link']})\n\n")
            f.write("---\n\n")

    return filepath


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /start — приветствие и запрос тикера."""
    user_id = update.effective_user.id
    user_state[user_id] = {"step": "await_ticker"}

    await update.message.reply_html(
        "👋 <b>Инвестиционный дайджест</b>\n\n"
        "Я соберу новости по твоему тикеру из 5 финансовых каналов.\n\n"
        "📝 <b>Напиши тикер или название</b> (например: <code>SBER</code>, <code>Газпром</code>, <code>AAPL</code>)\n"
        "💡 Или сразу с периодом: <code>SBER месяц</code>, <code>Газпром квартал</code>",
        reply_markup=reply_keyboard(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /help."""
    await update.message.reply_html(
        "<b>Команды:</b>\n"
        "/start — новый запрос (показывает клавиатуру)\n"
        "/new — быстрый новый запрос\n"
        "/fetch — собрать свежие посты из каналов (запускай периодически)\n"
        "/help — это сообщение\n\n"
        "<b>Как пользоваться:</b>\n"
        "1. Напиши тикер: <code>SBER</code> или <code>Газпром</code>\n"
        "2. Выбери период кнопкой снизу 👇\n"
        "   Или сразу: <code>SBER день</code>, <code>SBER неделя</code>, <code>Газпром месяц</code>, <code>AAPL квартал</code>\n"
        "3. Получи хронологический список новостей\n\n"
        "<b>Периоды:</b> день / неделя / месяц / квартал / полугодие / год\n"
        "<b>Кнопки снизу:</b> 📅 День, 📅 Неделя, 📅 Месяц, 📅 Квартал, 📅 Полугодие, 📅 Год, 🔄 Новый запрос, ℹ️ Помощь"
    )


async def fetch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /fetch — запуск сбора данных (делегирует в fetch.py)."""
    msg = await update.message.reply_html("⏳ Запускаю сбор постов за последние 30 дней…")

    try:
        # Импортируем и запускаем fetch
        from src.fetch import fetch_all_channels
        from src.config import FETCH_CFG

        limit = FETCH_CFG.get("limit_per_channel", 1000)
        count = await fetch_all_channels(days_back=30, limit_per_channel=limit)

        await msg.edit_text(
            f"✅ Сбор завершён. Добавлено новых постов: <b>{count}</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        log.exception("Ошибка при /fetch")
        await msg.edit_text(
            f"❌ Ошибка при сборе: <code>{e}</code>",
            parse_mode=ParseMode.HTML,
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текста: тикер, тикер+период, или кнопки Reply-клавиатуры."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    state = user_state.get(user_id, {})

    # Кнопки Reply-клавиатуры
    if text == "🔄 Новый запрос":
        user_state[user_id] = {"step": "await_ticker"}
        await update.message.reply_html(
            "🔄 <b>Новый запрос</b>\n\nНапиши тикер или название (например: <code>SBER</code>, <code>Газпром</code>)",
            reply_markup=reply_keyboard(),
        )
        return

    if text == "ℹ️ Помощь":
        await help_cmd(update, context)
        return

    # Кнопки периодов из Reply-клавиатуры
    reply_period_map = {
        "📅 День": "day",
        "📅 Неделя": "week",
        "📅 Месяц": "month",
        "📅 Квартал": "quarter",
        "📅 Полугодие": "half_year",
        "📅 Год": "year",
    }
    if text in reply_period_map:
        period_key = reply_period_map[text]
        ticker = state.get("query")
        if not ticker:
            await update.message.reply_html(
                "Сначала напиши тикер (например: <code>SBER</code>).",
                reply_markup=reply_keyboard(),
            )
            return
        await do_search_and_reply(update, ticker, period_key)
        return

    # Парсим "тикер период" в одном сообщении
    ticker, period_key = parse_ticker_period(text)
    if ticker and period_key:
        await do_search_and_reply(update, ticker, period_key)
        return

    # Обычный ввод тикера (шаг 1)
    if state.get("step") != "await_ticker":
        user_state[user_id] = {"step": "await_ticker"}

    user_state[user_id] = {"step": "await_period", "query": text}

    await update.message.reply_html(
        f"✅ Принято: <b>{text}</b>\n\n"
        f"📅 <b>Выбери период кнопкой снизу 👇</b> или напиши: <code>{text} месяц</code>",
        reply_markup=reply_keyboard(),
    )


async def do_search_and_reply(update: Update, ticker: str, period_key: str) -> None:
    """Выполняет поиск и отправляет результат с кнопкой смены тикера."""
    await update.message.reply_html("🔍 Ищу новости…", reply_markup=reply_keyboard())

    results = search_messages(ticker, period_key, max_items=50)
    parts = format_digest(results, ticker, period_key)

    # Сохраняем в Reports/
    md_path = save_digest_to_md(results, ticker, period_key)

    # Inline-кнопка "Сменить тикер" под результатом
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Сменить тикер", callback_data="change_ticker"),
        InlineKeyboardButton("📅 Сменить период", callback_data="change_period"),
    ]])

    for i, part in enumerate(parts):
        if i == 0:
            await update.message.reply_html(part, disable_web_page_preview=True, reply_markup=keyboard)
        else:
            await update.message.reply_html(part, disable_web_page_preview=True)

    # Подтверждение сохранения
    await update.message.reply_html(
        f"📄 Сохранено в <code>{md_path.name}</code>",
        reply_markup=reply_keyboard(),
    )

    # Состояние: можно сразу сменить тикер/период
    user_state[update.effective_user.id] = {"step": "done", "query": ticker, "period": period_key}


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатия inline-кнопок: период, смена тикера, смена периода."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data
    state = user_state.get(user_id, {})

    # Inline-кнопка периода (period:month)
    if data.startswith("period:"):
        period_key = data.split(":", 1)[1]
        ticker = state.get("query")
        if not ticker:
            await query.edit_message_text("Сначала напиши тикер (/start).")
            return
        await query.edit_message_text("🔍 Ищу новости…")
        results = search_messages(ticker, period_key, max_items=50)
        parts = format_digest(results, ticker, period_key)

        # Сохраняем в Reports/
        md_path = save_digest_to_md(results, ticker, period_key)

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Сменить тикер", callback_data="change_ticker"),
            InlineKeyboardButton("📅 Сменить период", callback_data="change_period"),
        ]])
        # Первую часть редактируем, остальные — новыми сообщениями
        for i, part in enumerate(parts):
            if i == 0:
                await query.edit_message_text(part, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=keyboard)
            else:
                await query.message.reply_html(part, disable_web_page_preview=True)

        # Подтверждение сохранения
        await query.message.reply_html(
            f"📄 Сохранено в <code>{md_path.name}</code>",
        )

        user_state[user_id] = {"step": "done", "query": ticker, "period": period_key}
        return

    # Inline-кнопка "Сменить тикер"
    if data == "change_ticker":
        user_state[user_id] = {"step": "await_ticker"}
        await query.edit_message_text(
            "🔄 <b>Смена тикера</b>\n\nНапиши новый тикер или название:",
            parse_mode=ParseMode.HTML,
        )
        return

    # Inline-кнопка "Сменить период"
    if data == "change_period":
        ticker = state.get("query")
        if not ticker:
            await query.edit_message_text("Сначала напиши тикер (/start).")
            return
        user_state[user_id] = {"step": "await_period", "query": ticker}
        await query.edit_message_text(
            f"📅 <b>Смена периода для {ticker}</b>\n\nВыбери период:",
            parse_mode=ParseMode.HTML,
            reply_markup=period_keyboard(),
        )
        return


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальный обработчик ошибок."""
    log.exception("Ошибка в боте: %s", context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_html(
            f"❌ Произошла ошибка: <code>{context.error}</code>"
        )


def main() -> None:
    """Запуск бота (polling)."""
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    app = Application.builder().token(BOT_TOKEN).build()

    # Хендлеры
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", start))  # /new = быстрый старт
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("fetch", fetch_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(error_handler)

    log.info("Бот запущен (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()