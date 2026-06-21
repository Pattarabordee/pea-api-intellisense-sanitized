from __future__ import annotations

from typing import Any


CONFIDENT_MATCH_LEVELS = {"cb", "recloser", "switch", "transformer"}


def build_customer_facing_gate(
    *,
    webex_device_interruption_class: str | None,
    webex_open_close_minutes: float | int | str | None,
    match_level: str | None,
    match_confidence: float | int | str | None,
    affected_count: int | str | None,
    active_ais_outage_confirmed: bool = False,
) -> dict[str, Any]:
    """Classify whether a shadow ETR is usable as a customer-facing candidate."""
    normalized_match_level = (match_level or "").lower()
    confidence = _float_or_none(match_confidence) or 0.0
    affected = _int_or_zero(affected_count)
    interruption_class = webex_device_interruption_class or "unknown"

    if affected <= 0 or confidence <= 0:
        gate = "review_only"
        reason = "no_confident_ais_customer_match"
        requires_active_confirmation = False
    elif normalized_match_level == "feeder":
        gate = "review_only"
        reason = "feeder_fallback_is_shadow_only"
        requires_active_confirmation = True
    elif interruption_class == "momentary_le_1m" and not active_ais_outage_confirmed:
        gate = "review_only"
        reason = "momentary_webex_operation_requires_active_ais_outage_confirmation"
        requires_active_confirmation = True
    elif interruption_class in {"short_le_5m"} and not active_ais_outage_confirmed:
        gate = "review_only"
        reason = "short_webex_interruption_requires_active_ais_outage_confirmation"
        requires_active_confirmation = True
    elif normalized_match_level in CONFIDENT_MATCH_LEVELS and interruption_class in {
        "sustained_candidate",
        "open_gt_5m",
        "trip_no_open_close",
    }:
        gate = "shadow_etr_candidate"
        reason = "confident_protection_match_with_sustained_like_webex_state"
        requires_active_confirmation = False
    elif normalized_match_level in CONFIDENT_MATCH_LEVELS and active_ais_outage_confirmed:
        gate = "shadow_etr_candidate"
        reason = "confident_protection_match_with_active_ais_outage_confirmation"
        requires_active_confirmation = False
    else:
        gate = "review_only"
        reason = "insufficient_webex_device_state_for_customer_facing_etr"
        requires_active_confirmation = True

    return {
        "delivery_scope": "shadow_only",
        "customer_facing_gate": gate,
        "reason": reason,
        "webex_device_interruption_class": interruption_class,
        "webex_open_close_minutes": _float_or_none(webex_open_close_minutes),
        "active_ais_outage_confirmed": active_ais_outage_confirmed,
        "requires_active_ais_confirmation": requires_active_confirmation,
    }


def _float_or_none(value: float | int | str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: int | str | None) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
