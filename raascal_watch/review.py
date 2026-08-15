from __future__ import annotations

"""Reviewer-feedback vocabulary for calibrating RaaScal Watch.

The first calibration release intentionally uses a small, explicit taxonomy.
Values are stored as stable machine-readable codes while the UI renders the
human-readable labels and descriptions below.
"""

REVIEW_DECISIONS: tuple[dict[str, str], ...] = (
    {
        "value": "actionable",
        "label": "Actionable",
        "description": "An owner should investigate or change a control now.",
    },
    {
        "value": "monitor",
        "label": "Monitor",
        "description": "Relevant enough to track, but not an immediate action.",
    },
    {
        "value": "informational",
        "label": "Informational",
        "description": "Useful context with no current operational response.",
    },
    {
        "value": "false_positive",
        "label": "False positive",
        "description": "Not meaningfully connected to this profile or risk path.",
    },
)

GUIDANCE_RATINGS: tuple[dict[str, str], ...] = (
    {"value": "useful", "label": "Useful"},
    {"value": "partly_useful", "label": "Partly useful"},
    {"value": "not_useful", "label": "Not useful"},
)

REVIEW_REASON_GROUPS: tuple[dict[str, object], ...] = (
    {
        "label": "Why it may matter",
        "items": (
            ("credible_influence_path", "Credible influence path"),
            ("advance_information_access", "Advance-information concern"),
            ("data_oracle_dependency", "Data or oracle dependency"),
            ("material_economic_exposure", "Material economic exposure"),
            ("settlement_urgent", "Near settlement"),
            ("downstream_operational_impact", "Meaningful downstream impact"),
        ),
    },
    {
        "label": "Why it may be noise",
        "items": (
            ("incidental_mention", "Incidental mention"),
            ("wrong_profile", "Wrong organization or theme"),
            ("wrong_role", "Wrong organizational role"),
            ("duplicate_or_related", "Duplicate or related contract"),
            ("not_influenceable", "Outcome not realistically influenceable"),
            ("insufficient_economic_exposure", "Economic exposure too small"),
            ("missing_context", "Insufficient context"),
        ),
    },
    {
        "label": "Guidance corrections",
        "items": (
            ("wrong_owner", "Wrong suggested owner"),
            ("missing_next_step", "Missing an important next step"),
            ("overly_generic_guidance", "Guidance was too generic"),
        ),
    },
)

REVIEW_DECISION_VALUES = frozenset(item["value"] for item in REVIEW_DECISIONS)
GUIDANCE_RATING_VALUES = frozenset(item["value"] for item in GUIDANCE_RATINGS)
REVIEW_REASON_VALUES = frozenset(
    code
    for group in REVIEW_REASON_GROUPS
    for code, _label in group["items"]  # type: ignore[index]
)

REVIEW_DECISION_LABELS = {
    item["value"]: item["label"] for item in REVIEW_DECISIONS
}
GUIDANCE_RATING_LABELS = {
    item["value"]: item["label"] for item in GUIDANCE_RATINGS
}
REVIEW_REASON_LABELS = {
    code: label
    for group in REVIEW_REASON_GROUPS
    for code, label in group["items"]  # type: ignore[index]
}


def normalize_reason_codes(values: list[str] | tuple[str, ...]) -> list[str]:
    """Return unique supported reason codes in stable input order."""

    output: list[str] = []
    for value in values:
        clean = str(value).strip().lower()
        if clean in REVIEW_REASON_VALUES and clean not in output:
            output.append(clean)
    return output
