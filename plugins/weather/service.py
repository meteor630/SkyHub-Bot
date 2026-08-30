"""Получение и разбор METAR/TAF (ТЗ §41, "Авиационная информация").

Источник -- бесплатный публичный API aviationweather.gov (официальный
сервис NOAA/NWS США, но отдаёт данные по аэропортам всего мира, ключ не
нужен). Выбор сделан осознанно ради нулевого порога входа: если у вас
есть подписка на другой провайдер (CheckWX, AVWX и т.п.), достаточно
переписать :func:`fetch_raw` -- остальной плагин от источника не зависит.

METAR разбирается на структурированные поля через пакет ``metar``. Полный
парсинг TAF (прогноз на несколько периодов вперёд) -- заметно более
сложная задача; вместо частичной/ненадёжной реализации TAF показывается
как есть, официальным текстом в code-block -- это то, что обычно и
делают даже крупные авиационные боты.
"""
from __future__ import annotations

import logging

import aiohttp
from metar import Metar

logger = logging.getLogger("skyhub.weather")

API_BASE = "https://aviationweather.gov/api/data"
REQUEST_TIMEOUT_SECONDS = 10.0


class WeatherError(Exception):
    """Не удалось получить или разобрать погодную сводку."""


async def fetch_raw(session: aiohttp.ClientSession, report_type: str, icao: str) -> str:
    """``report_type`` -- ``"metar"`` или ``"taf"``."""
    url = f"{API_BASE}/{report_type}"
    params = {"ids": icao.upper(), "format": "raw"}
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)) as resp:
            if resp.status != 200:
                raise WeatherError(f"Сервис погоды ответил статусом {resp.status}")
            text = (await resp.text()).strip()
    except aiohttp.ClientError as exc:
        raise WeatherError("Не удалось связаться с сервисом авиационной погоды") from exc

    if not text:
        raise WeatherError(f"Для {icao.upper()} нет свежей сводки {report_type.upper()} -- проверьте код ICAO.")
    return text


def parse_metar(raw: str) -> Metar.Metar:
    # aviationweather.gov отдаёт строку с префиксом "METAR " -- разбирать
    # нужно только сам отчёт.
    body = raw.removeprefix("METAR ").strip()
    try:
        return Metar.Metar(body)
    except Metar.ParserError as exc:
        raise WeatherError(f"Не удалось разобрать METAR: {exc}") from exc


def strip_report_prefix(raw: str, report_type: str) -> str:
    prefix = report_type.upper() + " "
    return raw.removeprefix(prefix).strip()
