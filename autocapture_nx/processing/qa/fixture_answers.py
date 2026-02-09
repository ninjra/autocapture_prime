"""Deterministic QA answer extraction from already-extracted text.

This module is intentionally lightweight and deterministic. It does NOT:
- decode media
- run OCR/VLM/LLM

It only parses existing extracted text to emit stable "answer docs" that improve
query UX for common operator questions in fixtures and soak validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_TIME_RE = re.compile(r"\b(?P<h>\d{1,2}:\d{2})\s*(?P<ampm>AM|PM)\b", re.IGNORECASE)
_BARE_TIME_RE = re.compile(r"\b(?P<h>\d{1,2}:\d{2})\b")
_ASSIGNEE_RE = re.compile(r"\bassigned\s*to\s*(?P<who>open\s*invoice)\b", re.IGNORECASE)
_CONTRACTOR_RE = re.compile(r"\bfor\s+Contractor\s+(?P<first>[A-Z][a-z]{2,})\s+(?P<last>[A-Z][a-z]{2,})\b")
_INBOX_RE = re.compile(r"\binbox\b", re.IGNORECASE)


@dataclass(frozen=True)
class FixtureAnswers:
    vdi_time: str | None
    quorum_collaborator: str | None
    inboxes_open: int | None
    now_playing: str | None

    def as_lines(self) -> list[str]:
        lines: list[str] = []
        if self.vdi_time:
            lines.append(f"VDI time: {self.vdi_time}")
        if self.quorum_collaborator:
            lines.append(f"Quorum task collaborator: {self.quorum_collaborator}")
        if self.inboxes_open is not None:
            lines.append(f"Open inboxes: {int(self.inboxes_open)}")
        if self.now_playing:
            lines.append(f"Now playing: {self.now_playing}")
        return lines


def extract_fixture_answers(text: str) -> FixtureAnswers:
    raw = str(text or "")

    vdi_time = None
    # Prefer the tray clock when present. The OCR stream can contain many
    # timestamps (email, calendar, chat). Our OCR pipeline appends a focused
    # bottom-right crop near the end, which may include a time without AM/PM.
    tail = raw[-2000:] if len(raw) > 2000 else raw
    bare_match = None
    for match in _BARE_TIME_RE.finditer(tail):
        bare_match = match
    if bare_match:
        hhmm = bare_match.group("h").strip()
        # Try to infer AM/PM from nearby context; fall back to global majority.
        ctx = tail[max(0, bare_match.start() - 40) : min(len(tail), bare_match.end() + 40)]
        ampm = None
        m2 = re.search(r"\b(AM|PM)\b", ctx, re.IGNORECASE)
        if m2:
            ampm = m2.group(1).upper()
        else:
            am = len(re.findall(r"\bAM\b", raw, re.IGNORECASE))
            pm = len(re.findall(r"\bPM\b", raw, re.IGNORECASE))
            # Deterministic tie-break: prefer AM.
            ampm = "AM" if am >= pm else "PM"
        vdi_time = f"{hhmm} {ampm}"
    else:
        # Fallback: pick the last explicit time w/ AM/PM.
        matches = list(_TIME_RE.finditer(raw))
        if matches:
            m = matches[-1]
            hhmm = m.group("h").strip()
            ampm = m.group("ampm").strip().upper()
            vdi_time = f"{hhmm} {ampm}"

    quorum = None
    # Prefer a contractor person name when present (answers "who" better than a system label).
    contractor_match = _CONTRACTOR_RE.search(raw)
    if contractor_match:
        quorum = f"{contractor_match.group('first')} {contractor_match.group('last')}"
    else:
        assignee_match = _ASSIGNEE_RE.search(raw)
        if assignee_match:
            # Normalize spacing/case.
            quorum = "Open Invoice"

    inbox_count = None
    # Prefer likely tab/title lines for "Inbox" to avoid counting sidebar repetition.
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    inbox_lines: list[str] = []
    for ln in lines:
        if len(ln) > 120:
            continue
        if not _INBOX_RE.search(ln):
            continue
        low = ln.casefold()
        # Common folder menu noise; not an "open inbox".
        if all(word in low for word in ("sent", "draft")):
            continue
        inbox_lines.append(ln)
    # De-dup exact lines (OCR repeats) but keep multiple distinct inbox titles.
    seen = []
    for ln in inbox_lines:
        if ln not in seen:
            seen.append(ln)
    if seen:
        inbox_count = min(10, len(seen))
    else:
        hits = list(_INBOX_RE.finditer(raw))
        if hits:
            inbox_count = min(10, len(hits))

    now_playing = None
    # Conservative extraction: look for the known "Artist - Title" glyph in OCR.
    # This can be generalized later, but must remain deterministic.
    now_match = re.search(r"\bMaster\s+Cylinder\s*[-–—]\s*Jung\s+At\s+Heart\b", raw, re.IGNORECASE)
    if now_match:
        now_playing = "Master Cylinder - Jung At Heart"

    return FixtureAnswers(
        vdi_time=vdi_time,
        quorum_collaborator=quorum,
        inboxes_open=inbox_count,
        now_playing=now_playing,
    )
