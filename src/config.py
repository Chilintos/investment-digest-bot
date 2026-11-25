"""
Конфигурация проекта: загрузка YAML, .env, aliases.json.
Аналог: VBA — чтение из Ini-файла / реестра / Dictionary.
"""
import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml
from dotenv import load_dotenv


# Загружаем .env один раз при импорте модуля
load_dotenv()


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Безопасное чтение переменной окружения."""
    return os.getenv(key, default)


def load_yaml_config(path: Union[str, Path] = "config.yaml") -> Dict[str, Any]:
    """Читает config.yaml и возвращает dict."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_aliases(path: Union[str, Path] = "config/aliases.json") -> Dict[str, List[str]]:
    """Читает словарь синонимов тикеров."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# Глобальные настройки (загружаются при импорте)
CFG = load_yaml_config()
ALIASES = load_aliases()

# Секреты из .env
API_ID = int(get_env("TELEGRAM_API_ID", "0"))
API_HASH = get_env("TELEGRAM_API_HASH", "")
BOT_TOKEN = get_env("TELEGRAM_BOT_TOKEN", "")

# Удобные доступы к часто используемым настройкам
CHANNELS = CFG.get("channels", [])
PERIODS = CFG.get("periods", {})
FETCH_CFG = CFG.get("fetch", {})
PATHS = CFG.get("paths", {})