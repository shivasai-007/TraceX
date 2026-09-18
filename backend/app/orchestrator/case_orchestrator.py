"""
Application / Case Orchestrator -- the top block of the architecture
diagram, and the single place where the MVP pipeline is expressed in
order:

  wallet address
    -> blockchain transaction collection      (ingestion/)
    -> transaction normalization + EDA        (normalization/)
    -> 1-3 hop graph traversal                (graph_engine/)
    -> wallet clustering (chain-specific)     (clustering/)
    -> transaction pattern detection          (patterns/)
    -> known address / entity matching        (entity_intel/, threat_intel/)
    -> VASP candidate generation              (attribution/)
    -> evidence-based attribution             (attribution/)
    -> risk fusion                            (risk/)
    -> timeline + alerts                      (this module)
    -> investigation dashboard / report       (api/, reporting/)

Kept deliberately readable top-to-bottom: this function IS the system's
methodology section, and it gets quoted in the generated report.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.attribution.vasp_candidate_engine import GHOST_CLUSTERS_NOTE, build_vasp_candidates
from app.clustering.btc_clustering import cluster_btc_wallets
from app.clustering.evm_clustering import cluster_evm_wallets
from app.core.logging import get_logger
from app.cross_chain.cross_chain_resolver import detect_cross_chain_exits
from app.db.models import Alert, WalletInvestigation
from app.entity_intel.known_entities import match_addresses
from app.graph_engine.graph_service import GraphEngine
from app.ingestion.provider_registry import get_provider
from app.normalization.normalize import normalize_transactions, to_dataframe
from app.patterns.rule_engine import run_rule_engine
from app.risk.ml_inference import RiskModel
from app.risk.risk_fusion import fuse_risk
from app.threat_intel.threat_intel_service import assess_threat_exposure

logger = get_logger(__name__)


async def _collect(address: str, chain: str, max_hops: int) -> tuple[list, list, dict]:
    """Hop-limited breadth-first collection. Hop 1 = the wallet itself;
    each further hop expands the most significant counterparties found so
    far. Expansion is capped so a single trace can't fan out into a
    full-chain crawl against a rate-limited free API tier."""
    provider = get_provider(chain)
    snapshot = await provider.get_wallet_snapshot(address)
    all_txs = await provider.get_transactions(address)
    visited = {address.lower()}
    frontier = set()

    # rank counterparties by value moved, expand only the top ones
    for tx in all_txs:
        for addr in (tx.from_address, tx.to_address):
            if addr and addr.lower() not in visited:
                frontier.add(addr.lower())

    per_hop_cap = {2: 15, 3: 8}
    for hop in range(2, max_hops + 1):
        cap = per_hop_cap.get(hop, 5)
        next_frontier: set[str] = set()
        for counterparty in list(frontier)[:cap]:
            if counterparty in visited:
                continue
            visited.add(counterparty)
            try:
                hop_txs = await provider.get_transactions(counterparty, limit=200)
            except Exception as exc:  # noqa: BLE001
                logger.warning("hop.collect_failed", address=counterparty, hop=hop, error=str(exc))
                continue
            all_txs.extend(hop_txs)
            for tx in hop_txs:
                for addr in (tx.from_address, tx.to_address):
                    if addr and addr.lower() not in visited:
                        next_frontier.add(addr.lower())
        frontier = next_frontier

    return all_txs, list(visited), {
        "balance": snapshot.balance,
        "first_activity": snapshot.first_activity.isoformat() if snapshot.first_activity else None,
        "last_activity": snapshot.last_activity.isoformat() if snapshot.last_activity else None,
        "total_transactions": snapshot.total_tx_count,
        "incoming_transactions": snapshot.incoming_count,
        "outgoing_transactions": snapshot.outgoing_count,
        "counterparty_count": len(snapshot.counterparties),
        "assets_used": sorted(snapshot.assets_used),
    }


def _build_timeline(df, patterns: list[dict], cross_chain: list[dict], summary: dict) -> list[dict]:
    events: list[dict] = []
    if summary.get("first_activity"):
        events.append({"timestamp": summary["first_activity"], "type": "first_activity",
                       "description": "First observed on-chain activity for this wallet."})
    if not df.empty:
        for _, row in df.iterrows():
            events.append({
                "timestamp": str(row["timestamp"]),
                "type": "funds_in" if row["direction"] == "incoming" else "funds_out",
                "description": f"{row['direction'].capitalize()} {row['value']:.6f} {row['asset']} "
                               f"{'from' if row['direction'] == 'incoming' else 'to'} {row['counterparty']}",
                "tx_hash": row["tx_hash"],
                "amount": float(row["value"]),
                "asset": row["asset"],
            })
    for p in patterns:
        if p.get("severity") in ("high", "critical"):
            events.append({
                "timestamp": None,
                "type": "suspicious_event",
                "description": f"{p['pattern']}: {p['explanation']}",
                "severity": p["severity"],
            })
    for c in cross_chain:
        events.append({
            "timestamp": c["timestamp"],
            "type": "cross_chain_exit",
            "description": f"Funds exited via bridge {c['bridge_name']} ({c['amount']:.6f} {c['asset']}).",
            "tx_hash": c["tx_hash"],
        })
    events.sort(key=lambda e: (e["timestamp"] is None, e["timestamp"] or ""))
    return events


def _generate_alerts(
    db: Session,
    case_id: str,
    investigation_id: str,
    patterns: list[dict],
    vasp_candidates: list[dict],
    cross_chain: list[dict],
) -> list[dict]:
    created: list[dict] = []

    def _add(alert_type: str, severity: str, message: str, payload: dict | None = None):
        alert = Alert(
            case_id=case_id,
            wallet_investigation_id=investigation_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
            payload=payload or {},
        )
        db.add(alert)
        created.append({"alert_type": alert_type, "severity": severity, "message": message})

    for p in patterns:
        if p["pattern"] == "mixer_interaction":
            _add("reaches_mixer", "critical",
                 "Traced funds interacted with a known mixer/tumbler.", {"evidence": p["evidence"]})
        elif p.get("severity") in ("high", "critical"):
            _add("high_risk_pattern", p["severity"],
                 f"High-risk pattern detected: {p['pattern']}.", {"explanation": p["explanation"]})

    for c in vasp_candidates:
        if c["confidence"] in ("attributed", "confirmed") and c["entity_type"] in ("vasp", "exchange", "custodian"):
            _add("reaches_vasp", "high",
                 f"Traced funds reached {c['name']} ({c['entity_type']}) at {c['hops']} hop(s).",
                 {"address": c["address"], "amount": c["amount_transferred"]})
        elif c["entity_type"] in ("exchange_candidate", "custodial_cluster_candidate"):
            _add("new_intermediary", "medium",
                 f"New exchange-like deposit cluster discovered at {c['address'][:12]}... (unattributed).",
                 {"evidence": c["evidence"][:2]})

    for c in cross_chain:
        _add("bridge_hop", "high",
             f"Funds moved through bridge {c['bridge_name']} -- destination chain unresolved.",
             {"tx_hash": c["tx_hash"]})

    db.commit()
    return created


async def run_investigation(db: Session, investigation: WalletInvestigation) -> WalletInvestigation:
    address = investigation.address.lower()
    chain = investigation.chain.value if hasattr(investigation.chain, "value") else str(investigation.chain)

    investigation.status = "running"
    db.commit()

    try:
        # 1-2) collect + normalize
        raw_txs, visited, summary = await _collect(address, chain, investigation.max_hops)
        normalized = normalize_transactions(raw_txs, address)
        df = to_dataframe(normalized)
        if not df.empty and summary.get("first_activity") and summary.get("last_activity"):
            span = (df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 86400
            summary["active_duration_days"] = round(span, 2)

        # 3) graph
        graph = GraphEngine()
        graph.add_wallet(address, chain, label="Suspect wallet")
        graph.add_transactions(normalized, chain)
        subgraph = graph.hop_subgraph(address, investigation.max_hops)

        # 4) chain-specific clustering
        if chain in ("ethereum", "polygon"):
            clustering = cluster_evm_wallets(df, address)
        elif chain == "bitcoin":
            clustering = cluster_btc_wallets([tx.raw for tx in raw_txs if tx.raw])
        else:
            clustering = {}

        # 5) known entity + threat intel matching
        touched = {address} | set(df["counterparty"].tolist() if not df.empty else [])
        entity_matches = match_addresses(db, {a.lower() for a in touched if a}, chain)
        for addr, entity in entity_matches.items():
            graph.tag_node(addr, kind="known_entity", entity_type=entity["entity_type"], entity_name=entity["name"])
        threat_result = assess_threat_exposure(db, {a.lower() for a in touched if a}, chain)

        # 6) pattern engine
        patterns = run_rule_engine(df, address, chain, list(entity_matches.values()), clustering)

        # 7) cross-chain exits
        if not df.empty:
            df["_chain"] = chain
        cross_chain = detect_cross_chain_exits(df, entity_matches)

        # 8) VASP candidates + evidence
        vasp_candidates = build_vasp_candidates(df, address, chain, graph.g, entity_matches, clustering)

        # 9) ML + risk fusion
        ml_result = RiskModel.instance().predict(normalized, address)
        risk_result = fuse_risk(patterns, threat_result, ml_result, summary)

        # 10) timeline + alerts
        timeline = _build_timeline(df, patterns, cross_chain, summary)
        alerts = _generate_alerts(db, investigation.case_id, investigation.id, patterns, vasp_candidates, cross_chain)

        graph.persist_to_neo4j()

        summary["graph"] = graph.to_frontend_json(address, subgraph)
        summary["nodes_traced"] = graph.node_count()
        summary["edges_traced"] = graph.edge_count()
        summary["addresses_visited"] = len(visited)
        summary["known_labels"] = [
            {"address": a, "name": e["name"], "type": e["entity_type"], "confidence": e["confidence"]}
            for a, e in entity_matches.items()
        ]
        summary["related_wallets"] = sorted(
            {c for c in (df["counterparty"].tolist() if not df.empty else [])}
        )[:100]

        investigation.summary = summary
        investigation.patterns = {"hits": patterns, "clustering": _jsonable(clustering)}
        investigation.vasp_candidates = {"candidates": vasp_candidates, "caveat": GHOST_CLUSTERS_NOTE}
        investigation.risk_result = risk_result
        investigation.timeline = {"events": timeline}
        investigation.cross_chain = {"events": cross_chain}
        investigation.status = "complete"
        investigation.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("investigation.complete", address=address, chain=chain,
                    risk=risk_result["risk_score"], alerts=len(alerts))

    except Exception as exc:  # noqa: BLE001
        logger.error("investigation.failed", address=address, chain=chain, error=str(exc))
        investigation.status = "failed"
        investigation.summary = {"error": str(exc)}
        db.commit()

    db.refresh(investigation)
    return investigation


def _jsonable(obj):
    """Clustering results contain sets/tuples in places; make them JSON-safe."""
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def run_investigation_sync(db: Session, investigation: WalletInvestigation) -> WalletInvestigation:
    """Synchronous entry point used when REDIS_URL is not configured."""
    return asyncio.run(run_investigation(db, investigation))
