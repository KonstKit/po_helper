"""PRD table extraction from Confluence HTML (wave D1.2).

Pure parsing extracted from the confluence router: given page HTML,
locate requirement tables and score/filter rows into structured
requirements. No HTTP or DB concerns - unit-testable in isolation.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def extract_requirements_from_html(html: str, page_id: str) -> dict:
    """Parse requirement tables out of a Confluence storage-format page."""
    soup = BeautifulSoup(html, "html.parser")
    requirements: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    parsed_rows = 0

    id_header_tokens = (
        "id",
        "requirement id",
        "req id",
        "story id",
        "key",
        "identifier",
        "#",
    )
    desc_header_tokens = (
        "requirement",
        "description",
        "summary",
        "user story",
        "story",
        "acceptance criteria",
        "criteria",
        "details",
        "behavior",
        "context",
        "decision",
    )
    prio_header_tokens = (
        "priority",
        "severity",
        "importance",
        "type",
        "category",
        "status",
    )
    requirement_signal_tokens = (
        "require",
        "story",
        "scenario",
        "acceptance",
        "criteria",
        "pre-condition",
        "post-condition",
        "constraint",
        "rule",
        "validation",
        "behavior",
        "goal",
        "epic",
        "feature",
    )
    noise_id_tokens = (
        "jira link",
        "link to design",
        "attachment",
        "attachments",
        "screenshot",
        "image",
        "figma",
    )
    ui_type_tokens = (
        "button",
        "page",
        "section",
        "dropdown",
        "dropdown menu",
        "input field",
        "chip",
        "snackbar",
        "checkbox",
        "table row",
        "pop-up",
        "popup",
        "menu",
    )

    def _clean_text(text: str) -> str:
        value = (text or "").replace("\xa0", " ")
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
        t = text.lower()
        return any(token in t for token in tokens)

    def _looks_like_url(text: str) -> bool:
        t = text.lower()
        return bool(
            re.search(r"https?://|www\.", t)
            or any(ext in t for ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", "/download/"))
        )

    def _direct_cells(row) -> list[Any]:
        return row.find_all(["td", "th"], recursive=False)

    def _extract_headers(table) -> list[str]:
        thead = table.find("thead")
        if thead:
            header_row = thead.find("tr")
            if header_row:
                headers = [
                    _clean_text(cell.get_text(" ", strip=True))
                    for cell in _direct_cells(header_row)
                ]
                return [h for h in headers if h]

        first_row = table.find("tr")
        if not first_row:
            return []

        headers = [
            _clean_text(cell.get_text(" ", strip=True))
            for cell in first_row.find_all("th", recursive=False)
        ]
        return [h for h in headers if h]

    def _looks_like_header_row(row, headers: list[str]) -> bool:
        if not headers:
            return False
        row_cells = [_clean_text(cell.get_text(" ", strip=True)) for cell in _direct_cells(row)]
        if len(row_cells) < len(headers):
            return False
        return row_cells[: len(headers)] == headers

    def _find_header_index(headers_l: list[str], tokens: tuple[str, ...]) -> Optional[int]:
        for idx, header in enumerate(headers_l):
            if any(token in header for token in tokens):
                return idx
        return None

    def _score_candidate(req_id_norm: str, desc_norm: str, prio_norm: str, structured: bool) -> int:
        req_l = req_id_norm.lower()
        desc_l = desc_norm.lower()
        prio_l = prio_norm.lower()
        score = 0

        if structured:
            score += 1
        if _contains_any(req_l, requirement_signal_tokens):
            score += 2
        if _contains_any(desc_l, ("given", "when", "then", "must", "should", "shall")):
            score += 1
        if _contains_any(desc_l, requirement_signal_tokens):
            score += 1
        if len(desc_norm.split()) >= 4:
            score += 1
        if prio_l in {"low", "medium", "high", "critical", "blocker"}:
            score += 1
        if _contains_any(prio_l, ui_type_tokens):
            score += 1

        if _contains_any(req_l, noise_id_tokens):
            score -= 3
        if _contains_any(desc_l, ("logo", "icon", "powered by", "report a bug")):
            score -= 2
        if _looks_like_url(desc_l) and len(desc_norm.split()) <= 8:
            score -= 2
        if len(desc_norm) < 3:
            score -= 2

        return score

    def _add_requirement(
        req_id: str,
        desc: str,
        prio: str,
        *,
        min_score: int,
        structured: bool,
    ) -> None:
        nonlocal parsed_rows
        req_id_norm = _clean_text(req_id)
        desc_norm = _clean_text(desc)
        prio_norm = _clean_text(prio)

        if not req_id_norm or not desc_norm:
            return
        if req_id_norm.lower() in {"id", "requirement"} and desc_norm.lower() in {
            "description",
            "summary",
        }:
            return
        score = _score_candidate(req_id_norm, desc_norm, prio_norm, structured)
        if score < min_score:
            return
        if prio_norm.lower() in {"", "-", "n/a"}:
            prio_norm = "Medium"
        if len(prio_norm) > 40:
            prio_norm = "Medium"
        if len(desc_norm) > 4000:
            desc_norm = desc_norm[:3997] + "..."

        dedupe_key = (req_id_norm.casefold(), desc_norm.casefold())
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        parsed_rows += 1
        requirements.append(
            {"id": req_id_norm, "description": desc_norm, "priority": prio_norm or "Medium"}
        )

    tables = soup.find_all("table")
    for table in tables:
        headers = _extract_headers(table)
        headers_l = [h.lower() for h in headers]
        header_blob = " ".join(headers_l)

        tbody = table.find("tbody")
        rows = (
            tbody.find_all("tr", recursive=False)
            if tbody
            else table.find_all("tr", recursive=False)
        )
        if not rows:
            continue

        first_col_sample = []
        for r in rows[:8]:
            cells = _direct_cells(r)
            if cells:
                first_col_sample.append(_clean_text(cells[0].get_text(" ", strip=True)).lower())
        first_col_blob = " ".join([x for x in first_col_sample if x])

        # Adaptive detection: explicit header signals OR semantic signals in first column.
        is_candidate = bool(headers) and (
            _contains_any(header_blob, requirement_signal_tokens) or len(headers) >= 2
        )
        if not is_candidate and first_col_blob:
            is_candidate = _contains_any(first_col_blob, requirement_signal_tokens)
        if not is_candidate:
            continue

        if _looks_like_header_row(rows[0], headers):
            rows = rows[1:]

        id_idx = _find_header_index(headers_l, id_header_tokens)
        desc_idx = _find_header_index(headers_l, desc_header_tokens)
        prio_idx = _find_header_index(headers_l, prio_header_tokens)
        structured = _contains_any(header_blob, requirement_signal_tokens)
        min_score = 0 if structured else 1

        for row in rows:
            cells = _direct_cells(row)
            if len(cells) < 2:
                continue

            fallback_id_idx = 0
            fallback_desc_idx = 1 if len(cells) > 1 else 0
            use_id_idx = id_idx if id_idx is not None and id_idx < len(cells) else fallback_id_idx
            use_desc_idx = (
                desc_idx if desc_idx is not None and desc_idx < len(cells) else fallback_desc_idx
            )
            use_prio_idx = prio_idx if prio_idx is not None and prio_idx < len(cells) else None

            req_id = _clean_text(cells[use_id_idx].get_text(" ", strip=True))
            desc = _clean_text(cells[use_desc_idx].get_text(" ", strip=True))
            if not desc and len(cells) > 2:
                # Some Confluence pages keep narrative text in the 3rd+ column.
                desc = _clean_text(cells[2].get_text(" ", strip=True))
            prio = (
                _clean_text(cells[use_prio_idx].get_text(" ", strip=True))
                if use_prio_idx is not None
                else (
                    _clean_text(cells[2].get_text(" ", strip=True)) if len(cells) > 2 else "Medium"
                )
            )
            _add_requirement(req_id, desc, prio, min_score=min_score, structured=structured)

    logger.info(
        "PRD extraction for page_id=%s: tables=%d rows_kept=%d requirements=%d",
        page_id,
        len(tables),
        parsed_rows,
        len(requirements),
    )
    return {"count": len(requirements), "requirements": requirements}


def _extract_section_text(soup: BeautifulSoup, titles: list[str]) -> str:
    # Find a header whose text matches any of the titles, return text until next header of same or higher level
    headers = soup.find_all(["h1", "h2", "h3", "h4"])
    target = None
    level = None
    for h in headers:
        txt = (h.get_text() or "").strip().lower()
        for t in titles:
            if t.lower() in txt:
                target = h
                level = int(h.name[1])
                break
        if target:
            break
    if not target:
        return ""
    texts: list[str] = []
    for el in target.next_siblings:
        if getattr(el, "name", None) in ("h1", "h2", "h3", "h4"):
            if int(el.name[1]) <= (level or 6):
                break
        if hasattr(el, "get_text"):
            texts.append(el.get_text(" ", strip=True))
    return "\n".join([t for t in texts if t])
