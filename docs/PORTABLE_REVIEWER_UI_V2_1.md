# Portable Reviewer UI v2.1 — Tonal Coherence Pass

## Goal

Fix the visual split where dark mode used a near-black application shell around a large bright paper sheet, and light mode retained a high-contrast dark folio rail inside a pale page.

## Changes

- Dark mode practice surface is now a deep warm paper tone rather than a bright cream sheet.
- Dark-mode question, answer, source, cloze input, and rating controls use one tonal material family.
- Light mode folio rail now uses warm stone/paper tones instead of near-black.
- Light-mode practice surface remains bone-paper but stays close to the surrounding shell in luminance.
- Accent hierarchy remains copper/gold for primary action, vermilion for source/seal, green for positive evidence.
- No StudyPack, StudyEvents, scoring, scheduling, sync, or evidence semantics changed.

## Verification

- `node --check portable-reviewer/app.js`
- `node --check portable-reviewer/sw.js`
- `pytest -q` — 44 passed
- `python3 scripts/portable_reviewer_smoke.py`
- `python3 scripts/portable_reviewer_ui_v2.py`
- `python3 scripts/study_protocol_browser_roundtrip.py`

Representative browser artifacts:

- `artifacts/ui-portable-reviewer-v02-flash-390-dark.png`
- `artifacts/ui-portable-reviewer-v02-cloze-430-light.png`
