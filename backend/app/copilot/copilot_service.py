"""
AI Copilot (architecture diagram block).

Turns a completed investigation's structured findings into a plain-language
narrative an investigator can paste into a case note -- and answers
follow-up questions about THAT investigation's data.

Two design rules, both deliberate:

1. The copilot only ever sees data the pipeline already produced. It is
   not given raw chain access and cannot "look things up" -- so it cannot
   introduce a fact that isn't in the evidence record.
2. It is strictly optional. With ANTHROPIC_API_KEY unset, these endpoints
   return a clear "not configured" response and every other feature of
   the platform works normally. An investigation tool must not depend on
   a language model to function.
"""
from __future__ import annotations

import json

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are an analytical assistant inside a law-enforcement cryptocurrency investigation platform.

You will be given the structured findings of one completed blockchain trace: wallet summary, detected
transaction patterns, VASP candidates with their evidence, risk components, and a timeline.

Rules you must follow:
- Only state things supported by the findings you are given. Never add addresses, exchange names,
  amounts or dates that are not present in the data.
- Distinguish clearly between what was OBSERVED on-chain, what was INFERRED by a heuristic, and what
  was ATTRIBUTED from an external intelligence source. The findings label each of these.
- Never assert that a wallet belongs to a person, company or exchange. Say what the evidence supports
  and what would be needed to confirm it (typically a request to the VASP through legal process).
- Write for an investigator: concise, factual, no marketing language, no hedging filler.
- If the findings are thin, say so plainly rather than padding."""


def _client():
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None, settings
    try:
        from anthropic import Anthropic

        return Anthropic(api_key=settings.anthropic_api_key), settings
    except ImportError:
        logger.warning("copilot.sdk_missing")
        return None, settings


def _findings_blob(investigation) -> str:
    return json.dumps(
        {
            "address": investigation.address,
            "chain": investigation.chain.value if hasattr(investigation.chain, "value") else investigation.chain,
            "summary": {k: v for k, v in (investigation.summary or {}).items() if k != "graph"},
            "risk": investigation.risk_result,
            "patterns": (investigation.patterns or {}).get("hits", []),
            "vasp_candidates": (investigation.vasp_candidates or {}).get("candidates", []),
            "cross_chain": (investigation.cross_chain or {}).get("events", []),
            "timeline": (investigation.timeline or {}).get("events", [])[:40],
        },
        default=str,
    )[:60_000]


def summarize_investigation(investigation) -> dict:
    client, settings = _client()
    if client is None:
        return {
            "available": False,
            "summary": None,
            "reason": "The AI copilot is not configured. Set ANTHROPIC_API_KEY in backend/.env to enable it.",
        }
    try:
        response = client.messages.create(
            model=settings.copilot_model,
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    "Write a case-note summary of this investigation for the lead investigator. "
                    "Cover: what the wallet did, the strongest patterns found, which VASP candidates "
                    "are worth pursuing and on what evidence, and what this trace cannot establish.\n\n"
                    f"FINDINGS:\n{_findings_blob(investigation)}"
                ),
            }],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return {"available": True, "summary": text}
    except Exception as exc:  # noqa: BLE001
        logger.warning("copilot.summarize_failed", error=str(exc))
        return {"available": False, "summary": None, "reason": f"Copilot request failed: {exc}"}


def ask_about_investigation(investigation, question: str) -> dict:
    client, settings = _client()
    if client is None:
        return {
            "available": False,
            "answer": None,
            "reason": "The AI copilot is not configured. Set ANTHROPIC_API_KEY in backend/.env to enable it.",
        }
    try:
        response = client.messages.create(
            model=settings.copilot_model,
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    f"Investigator's question: {question}\n\n"
                    "Answer using only the findings below. If the findings don't contain the answer, "
                    "say what data would be needed to answer it.\n\n"
                    f"FINDINGS:\n{_findings_blob(investigation)}"
                ),
            }],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return {"available": True, "answer": text}
    except Exception as exc:  # noqa: BLE001
        logger.warning("copilot.ask_failed", error=str(exc))
        return {"available": False, "answer": None, "reason": f"Copilot request failed: {exc}"}
