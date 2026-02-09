from __future__ import annotations


def action_from_risk(risk_class: str | None, mapping: dict) -> str | None:
    if risk_class is None:
        return None
    return mapping.get(risk_class)

