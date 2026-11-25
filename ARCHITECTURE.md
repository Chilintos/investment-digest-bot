# Architecture Overview — Investment Digest Bot

Документ для защиты проекта: демонстрирует использование **субагентов** и **скиллов** в Claude Code.

---

## 🏗 Общая архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                    MAIN AGENT (User-facing)                  │
│  • Принимает запрос: "дайджест по SBER за неделю"            │
│  • Парсит instrument + period (day/week/month/quarter/...)   │
│  • Вызывает: Agent(researcher, {instrument, period})         │
└──────────────────────────┬──────────────────────────────────┘
                           │ Agent tool
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              SUBAGENT: researcher (.claude/agents/)          │
│  • Получает instrument, period                               │
│  • Валидирует вход                                           │
│  • Загружает скилл: /skill news-digest                       │
│  • Выполняет логику скилла                                   │
│  • Возвращает результат главному агенту                      │
└──────────────────────────┬──────────────────────────────────┘
                           │ Skill execution
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  SKILL: news-digest (.claude/skills/)        │
│  1. Читает docs/sources.md (5 каналов)                       │
│  2. Определяет период в днях (day=1, week=7, month=30...)    │
│  3. Запускает: python -m main fetch --days N                 │
│  4. Запускает: python -m main search "SBER" --period week   │
│  5. Форматирует: заголовок (дата + канал) + полный текст     │
│  6. Сохраняет в Reports/ (Markdown)                          │
│  7. Добавляет дисклеймер                                     │
└──────────────────────────┬──────────────────────────────────┘
                           │ Python CLI
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    PROJECT MODULES (src/)                    │
│  • config.py  — YAML, .env, JSON → типизированные константы  │
│  • fetch.py   — Telethon userbot → CSV (инкрементально)      │
│  • search.py  — pandas: фильтр по aliases + словоформы + сортировка
│  • bot.py     — python-telegram-bot: Reply-клавиатура, inline-кнопки, разбивка длинных сообщений
└─────────────────────────────────────────────────────────────┘
```

---

## 🤖 Субагент: `researcher`

**Файл:** `.claude/agents/researcher.md`

```yaml
name: researcher
description: Субагент-исследователь для Investment Digest Bot. 
  Ищет посты по финансовому инструменту и периоду в 5 заданных 
  Telegram-каналах и возвращает хронологический список.
tools: Read, Bash
skills:
  - news-digest
```

**Вызов из основного агента:**
```python
# В контексте Claude Code:
Agent("researcher", {
    "instrument": "SBER",
    "period": "month"
})
```

**Что делает:**
1. Проверяет `instrument` и `period`
2. Активирует скилл `news-digest` (через `/skill news-digest`)
3. Возвращает **сырой результат** скилла без изменений

---

## 🔧 Скилл: `news-digest`

**Файл:** `.claude/skills/news-digest/SKILL.md`

```yaml
name: news-digest
description: Ищет посты по финансовому инструменту в заданных 
  Telegram-каналах за указанный период и возвращает их в 
  хронологическом порядке.
```

**Алгоритм скилла:**
```
1. READ docs/sources.md → список 5 каналов (username | name)
2. MAP period → days: day=1, week=7, month=30, quarter=90, half_year=180, year=365
3. RUN python -m main fetch --days <days>  (сбор через Telethon)
4. RUN python -m main search "<instrument>" --period <period> --max 50
5. FORMAT: заголовок (дата + канал — жирным) + полный текст + ссылка
6. SAVE: Reports/digest_<ticker>_<period>_<timestamp>.md
7. ADD disclaimer: "не финансовый совет, проверяй факты"
8. RETURN formatted list (части, если >4000 символов) или NOT_FOUND / ERROR
```

**Активация:**
```bash
/skill news-digest
# или в коде агента через skill tool
```

---

## 📦 Проектные модули (src/)

| Модуль | Роль | VBA-аналог |
|--------|------|------------|
| `config.py` | Единый источник конфигурации (YAML + .env + JSON) | `Dictionary` + `IniFile` |
| `fetch.py` | Telethon userbot → CSV (инкрементально, FloodWait handling) | `MSXML2.XMLHTTP` + `ADODB.Recordset` |
| `search.py` | pandas фильтрация + синонимы (aliases.json) + словоформы + сортировка | `AutoFilter` + `Sort` + `RegExp` |
| `bot.py` | Telegram Bot API: Reply-клавиатура (снизу), inline-кнопки, парсинг "тикер период", разбивка длинных сообщений, сохранение в Reports/ | `UserForm` + `Button_Click` + `CommandBar` |

---

## 🔄 Поток данных (Data Flow)

```
User: "SBER неделя"  (или нажимает 📅 Неделя на Reply-клавиатуре)
    │
    ▼
Main Agent парсит: instrument="SBER", period="week"
    │
    ▼ Agent(researcher, {...})
    │
    ▼
Subagent researcher валидирует → /skill news-digest
    │
    ▼ Skill news-digest
    │
    ├─► READ docs/sources.md (5 каналов)
    │
    ├─► RUN python -m main fetch --days 7
    │       │
    │       ▼ src/fetch.py → Telethon (userbot, твой аккаунт) → data/messages.csv
    │
    ├─► RUN python -m main search "SBER" --period week --max 50
    │       │
    │       ▼ src/search.py → pandas (aliases.json + словоформы) → filtered results
    │
    ├─► FORMAT: заголовок (дата + канал — <b>жирным</b>) + полный текст + ссылка
    │
    ├─► SPLIT: если >4000 символов → разбить на части
    │
    ├─► SAVE: Reports/digest_SBER_week_2026-11-25_14-30-45.md (Markdown с ## заголовками)
    │
    └─► RETURN parts → Subagent → Main Agent → USER (Reply-клавиатура + inline-кнопки)
```

---

## 🛡 Безопасность (для защиты)

- ✅ `.env` в `.gitignore` — секреты никогда не в репо
- ✅ `api_id`, `api_hash`, `bot_token` только через `config.get_env()`
- ✅ Userbot читает **только публичные** каналы
- ✅ Дисклеймер в каждом ответе бота и скилла
- ✅ Нет отправки данных во внешние сервисы

---

## 🧪 Тестирование (CLI команды)

```bash
# 1. Проверка конфига
python -c "import sys; sys.path.insert(0,'src'); from config import CHANNELS, ALIASES; print('Channels:', len(CHANNELS), 'Aliases:', len(ALIASES))"

# 2. Сбор данных (нужен .env)
python -m main fetch --days 30

# 3. Поиск (тест скилла)
python -m main search SBER --period month --max 10
python -m main search "Газпром" --period quarter
python -m main search AAPL --period half_year

# 4. Запуск бота
python -m main bot
```

---

## 📁 Структура файлов (итоговая)

```
investment-digest-bot/
├── main.py                      # Entry point: bot | fetch | search
├── requirements.txt             # deps
├── config.yaml                  # Каналы, периоды (day/week/month/quarter/half_year/year), лимиты
├── config/aliases.json          # Синонимы тикеров (10 шт.)
├── .env.example                 # Шаблон секретов
├── .gitignore                   # Защита секретов
├── data/messages.csv            # Хранилище (создаётся fetch)
├── Reports/                     # Markdown-дайджесты (создаётся ботом)
├── screenshots/                 # Для отчёта
├── docs/
│   ├── sources.md               # Список каналов (для скилла)
│   ├── План 30 дней.md
│   └── Список каналов-источников.md
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── fetch.py
│   ├── search.py
│   └── bot.py
├── .claude/
│   ├── agents/
│   │   └── researcher.md        # Субагент-исследователь
│   └── skills/
│       └── news-digest/
│           └── skill.md         # Скилл поиска новостей
└── README.md
```

---

## 🎯 Что демонстрирует этот проект

| Навык Claude Code | Где показан |
|-------------------|-------------|
| **Субагенты** (Agent tool) | `.claude/agents/researcher.md`, `data-fetcher.md` |
| **Скиллы** (/skill) | `.claude/skills/news-digest/SKILL.md`, `investment-digest.md` |
| **Конфигурация** (settings.json) | `.claude/settings.local.json` |
| **Артефакты** (Artifact tool) | Можно вынести дашборд/отчёт в HTML |
| **Мониторинг** (Monitor tool) | Можно следить за fetch-логами |
| **Код-ревью** (/code-review) | Скилл `code-review-standards.md` |

---

## 💬 Пример диалога на защите

**Эксперт:** "Как организован поиск новостей?"

**Вы:** "Основной агент принимает запрос, делегирует субагенту `researcher`, 
который активирует скилл `news-digest`. Скилл читает `docs/sources.md`, 
запускает `fetch` для сбора данных через Telethon, затем `search` через pandas 
с учётом синонимов из `aliases.json` и словоформ, сортирует хронологически 
и возвращает отформатированный список. Вся логика инкапсулирована в скилле, 
субагент — лишь тонкий прокси."