"""
Automated report generation: one standardized investigation report in
both JSON (machine-readable, for case files / further tooling) and PDF
(the artifact an investigator actually attaches to a case).

Sections follow the brief's required report structure exactly, including
the two sections most systems omit and courts care most about:
METHODOLOGY and LIMITATIONS. Those are generated from the actual run --
which chains, which heuristics fired, whether an ML model was loaded --
rather than being boilerplate.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.attribution.vasp_candidate_engine import GHOST_CLUSTERS_NOTE
from app.db.models import Case, WalletInvestigation

INK = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#6B7280")
RULE = colors.HexColor("#D8DEE6")
BAND = colors.HexColor("#F4F6F8")


def build_report_payload(case: Case, investigation: WalletInvestigation) -> dict:
    summary = investigation.summary or {}
    risk = investigation.risk_result or {}
    patterns = (investigation.patterns or {}).get("hits", [])
    candidates = (investigation.vasp_candidates or {}).get("candidates", [])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case": {
            "case_number": case.case_number,
            "crime_type": case.crime_type,
            "status": case.status.value,
            "victim_complaint": case.victim_complaint,
        },
        "subject": {
            "address": investigation.address,
            "chain": investigation.chain.value if hasattr(investigation.chain, "value") else investigation.chain,
            "seed_tx_hash": investigation.seed_tx_hash,
            "hops_traced": investigation.max_hops,
        },
        "transaction_summary": {
            k: summary.get(k)
            for k in (
                "balance", "first_activity", "last_activity", "total_transactions",
                "incoming_transactions", "outgoing_transactions", "counterparty_count",
                "assets_used", "nodes_traced", "edges_traced", "addresses_visited",
            )
        },
        "risk": risk,
        "detected_patterns": patterns,
        "vasp_candidates": candidates,
        "attribution_caveat": GHOST_CLUSTERS_NOTE,
        "cross_chain": (investigation.cross_chain or {}).get("events", []),
        "timeline": (investigation.timeline or {}).get("events", []),
        "important_wallets": summary.get("related_wallets", [])[:25],
        "known_labels": summary.get("known_labels", []),
        "data_sources": _data_sources(investigation),
        "methodology": _methodology(investigation),
        "limitations": _limitations(investigation),
    }


def _data_sources(investigation: WalletInvestigation) -> list[str]:
    chain = investigation.chain.value if hasattr(investigation.chain, "value") else investigation.chain
    sources = []
    if chain in ("ethereum", "polygon"):
        sources.append("Etherscan API v2 (unified multichain endpoint, chainid-parameterized)")
    if chain == "bitcoin":
        sources.append("Blockstream Esplora API (public Bitcoin indexer)")
    sources.append("TraceX Entity Intelligence Database (local known-address table)")
    return sources


def _methodology(investigation: WalletInvestigation) -> list[str]:
    chain = investigation.chain.value if hasattr(investigation.chain, "value") else investigation.chain
    risk = investigation.risk_result or {}
    ml = (risk.get("components") or {}).get("ml", {})
    steps = [
        f"Collected all available transactions for the subject address and expanded the trace to "
        f"{investigation.max_hops} hop(s) of counterparties, capped per hop to stay within API rate limits.",
        "Normalized every transaction to a chain-agnostic schema (hash, block, timestamp, from, to, "
        "asset, value, fee, direction) and de-duplicated overlapping records.",
        "Constructed a directed multigraph of wallets and transfers for traversal and visualization.",
    ]
    if chain in ("ethereum", "polygon"):
        steps.append(
            "Applied account-model clustering heuristics (exchange deposit-address detection, "
            "sweep-destination matching, rapid pass-through detection) per Victor (2020), "
            "'Address Clustering Heuristics for Ethereum'."
        )
    elif chain == "bitcoin":
        steps.append(
            "Applied UTXO-model clustering heuristics (common-input-ownership, change-output "
            "inference, consolidation detection), explicitly excluding transactions matching a "
            "CoinJoin signature from common-input clustering."
        )
    steps += [
        "Ran a rule engine of transaction-pattern detectors derived from FATF (2020) 'Virtual "
        "Assets Red Flag Indicators' -- fan-in/fan-out, consolidation, structuring, similar-value "
        "forwarding, rapid sequencing, and known-service interaction.",
        "Matched every address touched by the trace against the Entity Intelligence Database and "
        "threat-intelligence tables.",
        "Generated VASP candidates by combining direct address matches, cluster evidence, graph hop "
        "distance, transfer volume and recency -- each candidate carries its supporting evidence "
        "and a confidence tier (observed / inferred / attributed / confirmed).",
    ]
    if ml.get("available"):
        steps.append(
            f"Scored the wallet with a trained {ml.get('algorithm', 'ML')} behavioral model and fused "
            f"that score with the rule and threat-intelligence components at declared weights."
        )
    else:
        steps.append(
            "No trained ML model was loaded for this run; the risk score was computed from rule "
            "indicators and threat intelligence only, with the ML weight redistributed across them."
        )
    return steps


def _limitations(investigation: WalletInvestigation) -> list[str]:
    chain = investigation.chain.value if hasattr(investigation.chain, "value") else investigation.chain
    limits = [
        "Attribution is evidential, not conclusive. Candidates listed in this report are investigative "
        "leads requiring confirmation through lawful process (e.g. a request to the exchange), not "
        "proof of ownership.",
        GHOST_CLUSTERS_NOTE,
        f"The trace was limited to {investigation.max_hops} hop(s) with a per-hop expansion cap. Funds "
        "may have moved further than this report shows.",
        "Clustering heuristics are probabilistic. A deposit-address or common-input inference can group "
        "addresses that do not in fact share an owner, particularly where custodial services, "
        "multi-party wallets or payment processors are involved.",
        "Mixers, privacy protocols, cross-chain bridges and DeFi contracts break deterministic tracing. "
        "Where the report records a mixer or bridge interaction, the fund flow beyond that point is "
        "not established by on-chain data alone.",
        "Identity, KYC records, IP data, device data and beneficial ownership cannot be derived from "
        "blockchain data. These must be obtained from the VASP or service through legal process.",
        "Token values are reported in on-chain asset units at transaction time, not fiat value; "
        "fiat conversion requires a separate priced source.",
    ]
    if chain == "bitcoin":
        limits.append(
            "Bitcoin's UTXO model means a single transaction can involve many addresses; the "
            "directed edges in this report are a flattened representation of input/output sets."
        )
    return limits


def render_pdf(payload: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"TraceX investigation report {payload['case']['case_number']}",
    )
    base = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=base["Heading1"], fontSize=18, textColor=INK, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=base["Heading2"], fontSize=12, textColor=INK, spaceBefore=14, spaceAfter=6)
    body = ParagraphStyle("body", parent=base["BodyText"], fontSize=9.5, leading=14, textColor=INK)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, textColor=MUTED)

    story = []
    story.append(Paragraph("Cryptocurrency investigation report", h1))
    story.append(Paragraph(
        f"Case {payload['case']['case_number']} &nbsp;·&nbsp; {payload['case']['crime_type']} "
        f"&nbsp;·&nbsp; generated {payload['generated_at'][:19].replace('T', ' ')} UTC", small))
    story.append(Spacer(1, 10))

    subject = payload["subject"]
    risk = payload.get("risk", {})
    story.append(_kv_table([
        ("Subject address", subject["address"]),
        ("Blockchain", subject["chain"]),
        ("Hops traced", str(subject["hops_traced"])),
        ("Risk score", f"{risk.get('risk_score', 'n/a')}  ({risk.get('risk_band', 'n/a')})"),
    ]))

    story.append(Paragraph("Transaction summary", h2))
    ts = payload["transaction_summary"]
    story.append(_kv_table([
        ("Balance", str(ts.get("balance"))),
        ("First activity", str(ts.get("first_activity"))),
        ("Last activity", str(ts.get("last_activity"))),
        ("Total transactions", str(ts.get("total_transactions"))),
        ("Incoming / outgoing", f"{ts.get('incoming_transactions')} / {ts.get('outgoing_transactions')}"),
        ("Distinct counterparties", str(ts.get("counterparty_count"))),
        ("Assets involved", ", ".join(ts.get("assets_used") or []) or "n/a"),
        ("Graph size", f"{ts.get('nodes_traced')} nodes, {ts.get('edges_traced')} edges"),
    ]))

    story.append(Paragraph("Risk indicators", h2))
    indicators = risk.get("indicators", [])
    if indicators:
        rows = [["Indicator", "Severity", "Basis"]]
        for ind in indicators[:20]:
            rows.append([ind["indicator"], ind["severity"], Paragraph(ind.get("evidence", "")[:300], small)])
        story.append(_data_table(rows, [45 * mm, 20 * mm, 105 * mm]))
    else:
        story.append(Paragraph("No risk indicators were triggered for this wallet.", body))

    story.append(Paragraph("Detected transaction patterns", h2))
    patterns = payload.get("detected_patterns", [])
    if patterns:
        rows = [["Pattern", "Severity", "Explanation / research basis"]]
        for p in patterns[:20]:
            rows.append([
                p["pattern"], p.get("severity", ""),
                Paragraph(f"{p.get('explanation','')}<br/><font color='#6B7280'>{p.get('research_reference','')}</font>", small),
            ])
        story.append(_data_table(rows, [45 * mm, 20 * mm, 105 * mm]))
    else:
        story.append(Paragraph("No transaction patterns matched the rule engine for this wallet.", body))

    story.append(PageBreak())
    story.append(Paragraph("VASP candidates and supporting evidence", h2))
    candidates = payload.get("vasp_candidates", [])
    if candidates:
        for c in candidates[:10]:
            story.append(Paragraph(
                f"<b>{c['name']}</b> &nbsp;·&nbsp; {c['entity_type']} &nbsp;·&nbsp; "
                f"{c['exposure']} exposure at {c['hops']} hop(s) &nbsp;·&nbsp; confidence: {c['confidence']}", body))
            story.append(Paragraph(
                f"Address {c['address']} &nbsp;·&nbsp; {c['supporting_transactions']} supporting transaction(s) "
                f"&nbsp;·&nbsp; {c['amount_transferred']} transferred &nbsp;·&nbsp; last seen {c.get('last_interaction') or 'n/a'}",
                small))
            for ev in c.get("evidence", [])[:6]:
                story.append(Paragraph(f"• {ev}", small))
            story.append(Spacer(1, 8))
    else:
        story.append(Paragraph(
            "No VASP candidates were generated. This means the trace did not reach any address matching "
            "the Entity Intelligence Database, and no exchange-like deposit cluster met the evidence "
            "threshold -- not that no exchange was involved.", body))

    story.append(Paragraph("Attribution caveat", h2))
    story.append(Paragraph(payload["attribution_caveat"], body))

    if payload.get("cross_chain"):
        story.append(Paragraph("Cross-chain movement", h2))
        rows = [["Bridge", "Amount", "Transaction", "Destination"]]
        for c in payload["cross_chain"][:15]:
            rows.append([c["bridge_name"], f"{c['amount']} {c['asset']}", c["tx_hash"][:18] + "...", c["destination_chain"]])
        story.append(_data_table(rows, [40 * mm, 35 * mm, 50 * mm, 45 * mm]))

    story.append(Paragraph("Investigation timeline", h2))
    events = payload.get("timeline", [])
    if events:
        rows = [["When", "Event"]]
        for e in events[:30]:
            rows.append([
                (e.get("timestamp") or "")[:19].replace("T", " ") or "—",
                Paragraph(e.get("description", ""), small),
            ])
        story.append(_data_table(rows, [38 * mm, 132 * mm]))

    story.append(PageBreak())
    story.append(Paragraph("Data sources", h2))
    for s in payload["data_sources"]:
        story.append(Paragraph(f"• {s}", body))

    story.append(Paragraph("Methodology", h2))
    for i, step in enumerate(payload["methodology"], 1):
        story.append(Paragraph(f"{i}. {step}", body))
        story.append(Spacer(1, 3))

    story.append(Paragraph("Limitations", h2))
    for lim in payload["limitations"]:
        story.append(Paragraph(f"• {lim}", body))
        story.append(Spacer(1, 3))

    doc.build(story)
    return buffer.getvalue()


def _kv_table(pairs: list[tuple[str, str]]) -> Table:
    t = Table([[k, v] for k, v in pairs], colWidths=[45 * mm, 125 * mm])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("TEXTCOLOR", (1, 0), (1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
    ]))
    return t


def _data_table(rows: list[list], widths: list[float]) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), BAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def render_json(payload: dict) -> bytes:
    return json.dumps(payload, indent=2, default=str).encode("utf-8")
