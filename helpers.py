"""Helper utilities for the Retele Electrice Romania integration."""

from __future__ import annotations

import html
from typing import Any

from .const import MONTHS_NUM_RO


def decode_html_entities(text: str | None) -> str:
    """Decode HTML entities from portal messages."""
    if not text:
        return ""
    return html.unescape(str(text)).strip()


def normalize_title(text: str | None) -> str:
    """Format text in title case while preserving short uppercase acronyms."""
    if not text:
        return ""
    cleaned = decode_html_entities(text)
    words = cleaned.split()
    formatted = []
    for w in words:
        if w.isupper() and len(w) <= 3:
            formatted.append(w)
        else:
            formatted.append(w.capitalize())
    return " ".join(formatted)


def safe_float(value: Any, default: float | None = 0.0) -> float | None:
    """Safely convert a value to float."""
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return default


def format_date_ro_ddmmyyyy(date_str: str | None) -> str:
    """Format a DD.MM.YYYY date string with a Romanian month name."""
    if not date_str:
        return ""
    base = str(date_str).split(" ")[0].strip()
    parts = base.split(".")
    if len(parts) == 3:
        day_str, month_str, year_str = parts
        try:
            day_num = int(day_str)
            month_name = MONTHS_NUM_RO.get(month_str.zfill(2), month_str)
            return f"{day_num} {month_name} {year_str}"
        except ValueError:
            pass
    return base


def build_pod_address(pod: dict[str, Any]) -> str:
    """Build a formatted address string for a POD from Salesforce fields."""
    if not isinstance(pod, dict):
        return ""

    direct = pod.get("Address__c") or pod.get("Full_Address__c")
    if direct:
        return normalize_title(direct)

    parts: list[str] = []
    street = pod.get("Street__c") or pod.get("Street_Name__c") or ""
    number = pod.get("Street_Number__c") or pod.get("Number__c") or ""
    city = pod.get("City__c") or pod.get("Locality__c") or ""
    county = pod.get("County__c") or ""

    if street:
        s = normalize_title(street)
        if number:
            s = f"{s} nr. {number}"
        parts.append(s)
    if city:
        parts.append(normalize_title(city))
    if county:
        parts.append(f"jud. {normalize_title(county)}")

    return ", ".join(parts) if parts else "Address unavailable"
