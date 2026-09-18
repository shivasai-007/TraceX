"""
VASP Candidate Engine + Attribution / Evidence Engine.

This is the core module the whole brief is organized around. It does
NOT predict "wallet belongs to Exchange X". It combines:
  - direct known-address matches (Entity Intelligence DB)
  - chain-specific clustering output (deposit-address sweeps, common-input
    clusters)
  - graph hop distance from the investigated wallet
  - transaction/evidence volume and recency

...into a ranked list of VASP CANDIDATES, each carrying the evidence
that produced it and an explicit confidence tier:

  observed   -- directly seen on-chain (e.g. a transaction exists)
  inferred   -- derived via a heuristic (clustering, timing, similarity)
  attributed -- matched against external/off-chain intelligence
  confirmed  -- verified ground truth (subpoena return, KYC confirmation)

A candidate with NO known-entity match is still surfaced (as an
"unattributed cluster") when the evidence is strong -- per Ghost Clusters
(USENIX Security '25), even market-leading commercial attribution
providers have real, measured gaps, so absence of a name match must not
be read as absence of exchange-like behavior.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import networkx as nx
import pandas as pd

GHOST_CLUSTERS_NOTE = (
    "No attribution system has full coverage -- Lubbertsen et al. (USENIX Security '25) measured "
    "24.5-94.8% address-overlap accuracy even for the market-leading commercial provider against "
    "seized-service ground truth. Treat every candidate below as a lead to verify, not a verdict."
)


def _hop_distance(graph: nx.MultiDiGraph, focus: str, target: str) -> int | None:
    if focus not in graph or target not in graph:
        return None
    try:
        undirected = graph.to_undirected(as_view=True)
        return nx.shortest_path_length(undirected, focus, target)
    except nx.NetworkXNoPath:
        return None


def build_vasp_candidates(
    df: pd.DataFrame,
    focus_address: str,
    chain: str,
    graph: nx.MultiDiGraph,
    known_entity_matches: dict[str, dict],
    clustering_result: dict,
) -> list[dict]:
    candidates: dict[str, dict] = {}

    def _ensure(address: str, name: str | None, entity_type: str | None) -> dict:
        if address not in candidates:
            candidates[address] = {
                "address": address,
                "name": name or f"Unattributed cluster ({address[:10]}...)",
                "entity_type": entity_type or "unknown_candidate",
                "hops": _hop_distance(graph, focus_address, address),
                "amount_transferred": 0.0,
                "supporting_transactions": 0,
                "last_interaction": None,
                "supporting_wallet_cluster": set(),
                "evidence": [],
                "confidence": "inferred",
                "exposure": "indirect",
            }
        return candidates[address]

    # 1) direct known-entity matches on any address touched by this trace
    relevant_types = {"vasp", "exchange", "dex", "bridge", "custodian"}
    for address, entity in known_entity_matches.items():
        if entity["entity_type"] not in relevant_types:
            continue
        c = _ensure(address, entity["name"], entity["entity_type"])
        c["confidence"] = entity["confidence"]
        c["exposure"] = "direct" if c["hops"] in (0, 1) else "indirect"
        c["evidence"].append(
            f"Direct known-address match: {address} is attributed to {entity['name']} "
            f"(source: {entity['source']}, {entity.get('source_date') or 'date unknown'})."
        )

    # 2) fund-flow evidence: aggregate this trace's transactions per counterparty
    if not df.empty:
        for counterparty, group in df.groupby("counterparty"):
            if counterparty not in candidates:
                continue
            c = candidates[counterparty]
            c["amount_transferred"] += float(group["value"].sum())
            c["supporting_transactions"] += len(group)
            last_ts = group["timestamp"].max()
            if c["last_interaction"] is None or last_ts > c["last_interaction"]:
                c["last_interaction"] = last_ts
            c["evidence"].append(
                f"Fund-flow evidence: {len(group)} supporting transaction(s) totaling "
                f"{group['value'].sum():.6f} {group['asset'].iloc[0] if len(group) else ''}, "
                f"last on {last_ts}."
            )

    # 3) cluster-level evidence (EVM deposit-address sweeps -> named or unattributed exchange candidate)
    if chain in ("ethereum", "polygon"):
        for f in clustering_result.get("deposit_addresses", []):
            for dest in f.get("swept_to", []) or [f["wallet"]]:
                entity = known_entity_matches.get(dest)
                c = _ensure(dest, entity["name"] if entity else None, entity["entity_type"] if entity else "exchange_candidate")
                c["supporting_wallet_cluster"].add(f["wallet"])
                c["evidence"].append(
                    f"Cluster match: deposit address {f['wallet']} swept funds toward {dest} -- "
                    f"{f['evidence']}"
                )
                if c["confidence"] not in ("attributed", "confirmed"):
                    c["confidence"] = "inferred"
    elif chain == "bitcoin":
        for cluster in clustering_result.get("common_input_clusters", []):
            representative = cluster[0]
            entity = known_entity_matches.get(representative)
            c = _ensure(
                representative,
                entity["name"] if entity else None,
                entity["entity_type"] if entity else "custodial_cluster_candidate",
            )
            c["supporting_wallet_cluster"].update(cluster)
            c["evidence"].append(
                f"Cluster match: {len(cluster)} addresses share common-input ownership with {representative} "
                f"(see clustering evidence for the specific transaction)."
            )

    # finalize
    out = []
    for c in candidates.values():
        c["supporting_wallet_cluster"] = sorted(c["supporting_wallet_cluster"])
        c["last_interaction"] = c["last_interaction"].isoformat() if isinstance(c["last_interaction"], (pd.Timestamp, datetime)) else c["last_interaction"]
        c["amount_transferred"] = round(c["amount_transferred"], 8)
        out.append(c)

    # rank: attributed/confirmed + more evidence + closer hops first
    confidence_rank = {"confirmed": 3, "attributed": 2, "inferred": 1, "observed": 0}
    out.sort(
        key=lambda c: (
            confidence_rank.get(c["confidence"], 0),
            len(c["evidence"]),
            -(c["hops"] if c["hops"] is not None else 99),
        ),
        reverse=True,
    )
    return out
