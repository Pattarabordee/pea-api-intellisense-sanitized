from __future__ import annotations

import hashlib
import re
from typing import Iterable


_TRAILING_PUNCT = " \t\r\n.,;:()[]{}<>\"'"


def stable_id(prefix: str, *parts: object, length: int = 16) -> str:
    digest = hashlib.sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:length]}"


def normalize_device_id(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip(_TRAILING_PUNCT).upper()
    text = re.sub(r"\s+", "", text)
    return text or None


def normalize_feeder(value: object) -> str | None:
    text = normalize_device_id(value)
    if not text:
        return None
    match = re.search(r"\b([A-Z]{3}\d{2})\b", text)
    if match:
        return match.group(1)
    return text if re.fullmatch(r"[A-Z]{3}\d{2}", text) else None


def split_device_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    raw = str(value)
    if raw.lower() == "nan":
        return ()
    parts = re.split(r"\s*\|\s*|,\s*|;\s*", raw)
    normalized = []
    seen = set()
    for part in parts:
        item = normalize_device_id(part)
        if item and item not in seen:
            seen.add(item)
            normalized.append(item)
    return tuple(normalized)


def first_present(values: Iterable[object]) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() != "nan":
            return text
    return None

