# RaaScal Watch v0.6.0

## Reviewer feedback and calibration

Version 0.6.0 changes RaaScal Watch from a system that only surfaces candidate matches into one that can measure which matches create useful operational signal.

## Four reviewer decisions

Each organization or monitored theme attached to an active contract can receive one structured assessment:

- **Actionable** — an owner should investigate or change a control now.
- **Monitor** — relevant enough to track, but not an immediate action.
- **Informational** — useful context with no current operational response.
- **False positive** — not meaningfully connected to the profile or risk pathway.

The assessment applies to the profile match, not merely the contract. A MrBeast/YouTube contract can therefore be Actionable for YouTube, Monitor for Beast Industries, or vice versa.

## Optional calibration context

A reviewer can also record:

- why the match may matter;
- why it may be noise;
- whether the suggested next steps were useful;
- a corrected organizational role;
- a better internal owner; and
- a free-text note.

Reason tags are intentionally finite and explainable. They include credible influence paths, advance-information access, data/oracle dependency, economic exposure, settlement urgency, incidental mentions, wrong profiles, wrong roles, weak influenceability, missing context, wrong owners, and missing next steps.

## Dashboard changes

The active queue now shows profile-assessment progress for each contract. A contract can be:

- **Needs review** — no profile relationship has been assessed;
- **In review** — some, but not all, profile relationships have been assessed; or
- **Reviewed** — every profile relationship has structured feedback or a preserved legacy acknowledgement.

The dashboard adds:

- a **Reviewer decision** filter;
- **Unreviewed first** sorting;
- a calibration panel showing structured reviews, unreviewed profile matches, actionable/monitor rate, false-positive rate, and guidance usefulness;
- breakdowns by profile and risk pathway; and
- historical assessment labels in Archive without editable review controls.

## Database migration

The release creates a new `review_feedback` table with one latest assessment per profile match. Existing market history, matches, source baselines, notification states, acknowledgements, watchlist customizations, `.env`, and `.venv` are preserved.

Older binary acknowledgements remain visible as **Legacy reviewed**. They count as completed review work but are not mixed into structured decision rates.

## APIs and export

New endpoints:

```text
POST /api/matches/{match_id}/feedback
GET  /api/calibration
GET  /api/feedback
```

Structured feedback can be exported with:

```bash
raascal-watch export-feedback \
  --format csv \
  --view all \
  --output ./exports/reviewer_feedback.csv
```

The standard `raascal-watch export` command now also includes feedback fields.

## Important interpretation limit

Reviewer decisions are calibration data, not proof that an alert is objectively correct. A decision may reflect one reviewer, one organization’s risk appetite, incomplete public information, or a temporary operating context. RaaScal Watch should use the feedback to refine thresholds and workflows—not to claim ground truth or automatically accuse traders or organizations of misconduct.
