"""AI-EMS v5.1 Domain Data - 전력 도메인 기준값 및 용어사전."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DOMAIN_DIR = Path(__file__).parent


def load_json(filename: str) -> dict[str, Any]:
    """Load a domain JSON file by name."""
    filepath = _DOMAIN_DIR / filename
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def get_glossary() -> dict[str, Any]:
    """Load glossary.json — 178개 EMS 핵심 용어."""
    return load_json("glossary.json")


def get_voltage_limits() -> dict[str, Any]:
    """Load voltage_limits.json — 전압/주파수/예비력 정량 기준."""
    return load_json("voltage_limits.json")


def get_frequency_limits() -> dict[str, Any]:
    """Load frequency_limits.json — 주파수 유지기준."""
    return load_json("frequency_limits.json")


def get_thermal_ratings() -> dict[str, Any]:
    """Load thermal_ratings.json — 선로 열용량 기준."""
    return load_json("thermal_ratings.json")


def get_n1_criteria() -> dict[str, Any]:
    """Load n1_criteria.json — N-1 상정고장 판단기준."""
    return load_json("n1_criteria.json")
