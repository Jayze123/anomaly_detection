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


def lookup_risk_strict(
    rpm_table: list[dict],
    severity: int | None,
    occurrence: int | None,
    detection: int | None,
) -> tuple[int | None, str]:
    """
    Strict risk lookup: risk is only valid if a full predefined RPM row exists.
    Returns (risk_score, risk_class). risk_class will be 'REVIEW_REQUIRED' when unresolved.
    """
    score, risk_class = lookup_risk(rpm_table, severity, occurrence, detection)
    if score is None or risk_class is None:
        return None, "REVIEW_REQUIRED"
    return int(score), str(risk_class)
