"""Загружает config.yaml и рекурсивно объединяет с ним config.yaml
каждого плагина, чтобы ``plugins/<name>/config.yaml`` объявлял свои
значения по умолчанию только один раз, а корневой config.yaml мог
переопределять отдельные ключи под конкретное развёртывание, не
дублируя всю конфигурацию плагина (ТЗ §24)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} должен содержать YAML-словарь (mapping) на верхнем уровне")
    return data


def load_config(config_path: Path, plugins_dir: Path) -> dict[str, Any]:
    config = _read_yaml(config_path)
    config.setdefault("plugins", {})

    if plugins_dir.exists():
        for plugin_dir in sorted(plugins_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            plugin_config_path = plugin_dir / "config.yaml"
            if not plugin_config_path.exists():
                continue
            defaults = _read_yaml(plugin_config_path)
            existing = config["plugins"].get(plugin_dir.name, {})
            config["plugins"][plugin_dir.name] = _deep_merge(defaults, existing)

    return config
