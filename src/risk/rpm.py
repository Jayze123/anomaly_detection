from __future__ import annotations


def lookup_risk(
    rpm_table: list[dict],
    severity: int | None,
    occurrence: int | None,
    detection: int | None,
):
    if severity is None or occurrence is None or detection is None:
        return None, None
    for row in rpm_table:
        if (
            row.get("severity") == severity
            and row.get("occurrence") == occurrence
            and row.get("detection") == detection
        ):
            return row.get("risk_score"), row.get("risk_class")
    return None, None

