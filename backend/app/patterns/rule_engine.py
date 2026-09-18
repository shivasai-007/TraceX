"""
Topology / Rule Engine (matches the architecture diagram block of the
same name). Chain-agnostic: it operates on the already-normalized
transaction DataFrame (see app/normalization/normalize.py), so the same
detectors run whether the underlying chain was Ethereum or Bitcoin.

Every PatternHit is required to carry an explanation, evidence and a
research_reference -- this is what the project brief means by "not a
black-box prediction": an investigator (or a defense lawyer) can trace
every flagged pattern back to a specific rule and specific transactions.

Two kinds of findings feed the unified pattern list:
  1. Detectors defined in this file (fan-in/out, structuring, velocity...)
  2. Chain-specific clustering findings (deposit addresses, common-input
     clusters, ...), translated into the same PatternHit shape rather
     than duplicated here -- see translate_clustering_findings().
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

FATF_REF = "FATF (2020), Virtual Assets Red Flag Indicators of Money Laundering and Terrorist Financing"
VICTOR_REF = "Victor, F. (2020), Address Clustering Heuristics for Ethereum"
COMMON_INPUT_REF = "Meiklejohn et al. (2013) common-input-ownership heuristic; validated at scale by Elmougy & Liu (2023), Elliptic++"
GHOST_CLUSTERS_REF = "Lubbertsen, van Eeten & van Wegberg (2025), Ghost Clusters, USENIX Security '25 -- attribution coverage varies and is not ground truth"

STRUCTURING_THRESHOLDS = [10_000.0, 9_000.0, 2_000.0]  # illustrative reporting-style thresholds; tune per jurisdiction
FAN_THRESHOLD = 5
RAPID_GAP_SECONDS = 120
VELOCITY_MULTIPLIER = 5.0


@dataclass
class PatternHit:
    pattern: str
    severity: str  # info|low|medium|high|critical
    tx_hashes: list[str]
    explanation: str
    evidence: str
    research_reference: str
    confidence: str = "inferred"  # observed|inferred|attributed|confirmed
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- detectors

def detect_fan_in_fan_out(df: pd.DataFrame, focus_address: str) -> list[PatternHit]:
    hits = []
    incoming = df[df["direction"] == "incoming"]
    outgoing = df[df["direction"] == "outgoing"]

    in_counterparties = incoming["counterparty"].nunique()
    if in_counterparties >= FAN_THRESHOLD:
        hits.append(
            PatternHit(
                pattern="fan_in_many_to_one",
                severity="medium",
                tx_hashes=incoming["tx_hash"].tolist(),
                explanation=f"{focus_address} received funds from {in_counterparties} distinct addresses.",
                evidence=f"{in_counterparties} unique senders across {len(incoming)} incoming transactions.",
                research_reference=FATF_REF,
            )
        )
    out_counterparties = outgoing["counterparty"].nunique()
    if out_counterparties >= FAN_THRESHOLD:
        hits.append(
            PatternHit(
                pattern="fan_out_one_to_many",
                severity="medium",
                tx_hashes=outgoing["tx_hash"].tolist(),
                explanation=f"{focus_address} distributed funds to {out_counterparties} distinct addresses (fund splitting).",
                evidence=f"{out_counterparties} unique recipients across {len(outgoing)} outgoing transactions.",
                research_reference=FATF_REF,
            )
        )
    return hits


def detect_consolidation(df: pd.DataFrame, focus_address: str) -> list[PatternHit]:
    """Many small incoming tx clustered shortly before one larger outgoing tx."""
    hits = []
    incoming = df[df["direction"] == "incoming"].sort_values("timestamp")
    outgoing = df[df["direction"] == "outgoing"].sort_values("timestamp")
    if len(incoming) < FAN_THRESHOLD or outgoing.empty:
        return hits
    avg_in = incoming["value"].mean()
    for _, out in outgoing.iterrows():
        window = incoming[
            (incoming["timestamp"] <= out["timestamp"])
            & (incoming["timestamp"] >= out["timestamp"] - pd.Timedelta(hours=24))
        ]
        if len(window) >= FAN_THRESHOLD and out["value"] >= 0.8 * window["value"].sum() and out["value"] > avg_in:
            hits.append(
                PatternHit(
                    pattern="fund_consolidation",
                    severity="medium",
                    tx_hashes=window["tx_hash"].tolist() + [out["tx_hash"]],
                    explanation=(
                        f"{len(window)} incoming transactions in the preceding 24h were consolidated into "
                        f"one outgoing transfer of {out['value']:.6f} {out['asset']}."
                    ),
                    evidence=f"Sum of {len(window)} inbound tx ({window['value'].sum():.6f}) closely matches the outbound transfer.",
                    research_reference=FATF_REF,
                )
            )
    return hits


def detect_structuring(df: pd.DataFrame, focus_address: str) -> list[PatternHit]:
    """Repeated transfers clustered just under a round reporting-style
    threshold -- classic 'smurfing'. Thresholds are illustrative; tune
    STRUCTURING_THRESHOLDS to the fiat-equivalent limits relevant to your
    jurisdiction (this module works in on-chain asset units, so pair it
    with a price oracle in production for a real fiat-threshold check)."""
    hits = []
    for threshold in STRUCTURING_THRESHOLDS:
        band = df[(df["value"] >= threshold * 0.85) & (df["value"] < threshold)]
        if len(band) >= 3:
            hits.append(
                PatternHit(
                    pattern="repeated_transfers_near_threshold",
                    severity="high",
                    tx_hashes=band["tx_hash"].tolist(),
                    explanation=(
                        f"{len(band)} transactions fall just under the {threshold:g}-unit band, "
                        f"a pattern consistent with structuring to stay under reporting thresholds."
                    ),
                    evidence=f"Values: {sorted(band['value'].round(4).tolist())}",
                    research_reference=FATF_REF,
                )
            )
    return hits


def detect_sudden_large_transfer(df: pd.DataFrame, focus_address: str) -> list[PatternHit]:
    hits = []
    if len(df) < 4:
        return hits
    mean_v, std_v = df["value"].mean(), df["value"].std(ddof=0) or 0
    outliers = df[df["value"] > mean_v + VELOCITY_MULTIPLIER * (std_v or mean_v or 1)]
    for _, row in outliers.iterrows():
        hits.append(
            PatternHit(
                pattern="sudden_large_transfer",
                severity="high",
                tx_hashes=[row["tx_hash"]],
                explanation=f"Transfer of {row['value']:.6f} {row['asset']} is a major outlier versus this wallet's typical transaction size.",
                evidence=f"Wallet mean tx value {mean_v:.6f}, this transaction {row['value']:.6f}.",
                research_reference=FATF_REF,
            )
        )
    return hits


def detect_similar_value_forwarding(df: pd.DataFrame, focus_address: str) -> list[PatternHit]:
    hits = []
    outgoing = df[df["direction"] == "outgoing"]
    if len(outgoing) < 3:
        return hits
    rounded = outgoing["value"].round(4)
    for val, group in outgoing.groupby(rounded):
        if len(group) >= 3:
            hits.append(
                PatternHit(
                    pattern="similar_value_forwarding",
                    severity="medium",
                    tx_hashes=group["tx_hash"].tolist(),
                    explanation=f"{len(group)} outgoing transfers of ~{val:.4f} were sent to {group['counterparty'].nunique()} different address(es).",
                    evidence=f"Repeated near-identical amount ({val:.4f}) suggests a scripted payout (e.g. mule network disbursement).",
                    research_reference=FATF_REF,
                )
            )
    return hits


def detect_short_time_gap_transfers(df: pd.DataFrame, focus_address: str) -> list[PatternHit]:
    hits = []
    if len(df) < 3:
        return hits
    sorted_df = df.sort_values("timestamp").reset_index(drop=True)
    gaps = sorted_df["timestamp"].diff().dt.total_seconds()
    rapid_idx = gaps[gaps <= RAPID_GAP_SECONDS].index
    burst_hashes = []
    for i in rapid_idx:
        burst_hashes.extend([sorted_df.loc[i - 1, "tx_hash"], sorted_df.loc[i, "tx_hash"]])
    if len(rapid_idx) >= 3:
        hits.append(
            PatternHit(
                pattern="short_time_gap_transfers",
                severity="low",
                tx_hashes=sorted(set(burst_hashes)),
                explanation=f"{len(rapid_idx)} consecutive transaction pairs occurred within {RAPID_GAP_SECONDS}s of each other.",
                evidence="Sub-2-minute spacing across multiple transactions suggests scripted/automated activity rather than manual use.",
                research_reference=FATF_REF,
            )
        )
    return hits


def detect_service_interactions(df: pd.DataFrame, known_entities: list[dict]) -> list[PatternHit]:
    """Mixer / bridge / DEX interaction + repeated interaction with the
    same service, using matches against the Entity Intelligence DB."""
    hits: list[PatternHit] = []
    by_address = {e["address"].lower(): e for e in known_entities}
    entity_type_pattern = {"mixer": "mixer_interaction", "bridge": "bridge_interaction", "dex": "dex_interaction"}

    for _, row in df.iterrows():
        entity = by_address.get(row["counterparty"])
        if entity and entity["entity_type"] in entity_type_pattern:
            hits.append(
                PatternHit(
                    pattern=entity_type_pattern[entity["entity_type"]],
                    severity="critical" if entity["entity_type"] == "mixer" else "high",
                    tx_hashes=[row["tx_hash"]],
                    explanation=f"Transaction interacts with {entity['name']}, a known {entity['entity_type']}.",
                    evidence=f"Counterparty {row['counterparty']} matches Entity Intelligence DB entry '{entity['name']}' (source: {entity['source']}).",
                    research_reference=GHOST_CLUSTERS_REF if entity["entity_type"] != "mixer" else FATF_REF,
                    confidence=entity.get("confidence", "attributed"),
                )
            )

    counterparty_counts = df["counterparty"].value_counts()
    repeated = counterparty_counts[counterparty_counts >= FAN_THRESHOLD]
    for counterparty, count in repeated.items():
        hits.append(
            PatternHit(
                pattern="repeated_interaction_same_service",
                severity="low",
                tx_hashes=df[df["counterparty"] == counterparty]["tx_hash"].tolist(),
                explanation=f"{count} separate transactions with the same counterparty {counterparty}.",
                evidence=f"Repeated engagement ({count}x) with one address, consistent with a regular off-ramp/on-ramp relationship.",
                research_reference=FATF_REF,
            )
        )
    return hits


# ---------------------------------------------------------- clustering bridge

def translate_clustering_findings(clustering_result: dict, chain: str) -> list[PatternHit]:
    """Folds chain-specific clustering evidence (already evidence-bearing)
    into the same PatternHit shape, so the API/frontend deals with one
    unified pattern list regardless of which chain produced the finding."""
    hits: list[PatternHit] = []

    if chain in ("ethereum", "polygon"):
        for f in clustering_result.get("deposit_addresses", []):
            hits.append(
                PatternHit(
                    pattern="deposit_address_behavior",
                    severity="medium",
                    tx_hashes=[],
                    explanation=f"{f['wallet']} shows exchange-style deposit-address behavior.",
                    evidence=f['evidence'],
                    research_reference=VICTOR_REF,
                    confidence=f["confidence"],
                    extra={"wallet": f["wallet"], "swept_to": f["swept_to"]},
                )
            )
        for f in clustering_result.get("passthrough_wallets", []):
            occurrences = f.get("occurrences", 1)
            hits.append(
                PatternHit(
                    pattern="rapid_receive_forward",
                    severity="high" if occurrences >= 3 else "medium",
                    tx_hashes=f.get("tx_hashes", []),
                    explanation=(
                        f"{f['wallet']} passed funds straight through on {occurrences} occasion(s) "
                        f"(layering hop)."
                    ),
                    evidence=f["evidence"],
                    research_reference=VICTOR_REF,
                    confidence=f["confidence"],
                    extra={
                        "wallet": f["wallet"],
                        "occurrences": occurrences,
                        "median_gap_seconds": f.get("median_gap_seconds"),
                    },
                )
            )
    elif chain == "bitcoin":
        for f in clustering_result.get("common_input_evidence", []):
            hits.append(
                PatternHit(
                    pattern="common_input_cluster",
                    severity="medium",
                    tx_hashes=[f["tx_hash"]],
                    explanation=f"{len(f['addresses'])} addresses co-spent in one transaction (likely same owner).",
                    evidence=f["evidence"],
                    research_reference=COMMON_INPUT_REF,
                    confidence=f["confidence"],
                    extra={"addresses": f["addresses"]},
                )
            )
        for f in clustering_result.get("consolidation_events", []):
            hits.append(
                PatternHit(
                    pattern="fund_consolidation",
                    severity="medium",
                    tx_hashes=[f["tx_hash"]],
                    explanation="Many UTXOs consolidated into a single output.",
                    evidence=f["evidence"],
                    research_reference=FATF_REF,
                    confidence=f["confidence"],
                )
            )
        if clustering_result.get("excluded_coinjoin_txids"):
            hits.append(
                PatternHit(
                    pattern="mixer_interaction",
                    severity="critical",
                    tx_hashes=clustering_result["excluded_coinjoin_txids"],
                    explanation="One or more transactions match a CoinJoin / mixer signature (many inputs, many equal-value outputs).",
                    evidence="Excluded from common-input clustering because co-spending across unrelated participants is the intended behavior of a CoinJoin.",
                    research_reference=FATF_REF,
                    confidence="inferred",
                )
            )
    return hits


# ---------------------------------------------------------------- orchestrator

def run_rule_engine(
    df: pd.DataFrame,
    focus_address: str,
    chain: str,
    known_entities: list[dict],
    clustering_result: dict,
) -> list[dict]:
    hits: list[PatternHit] = []
    if not df.empty:
        hits += detect_fan_in_fan_out(df, focus_address)
        hits += detect_consolidation(df, focus_address)
        hits += detect_structuring(df, focus_address)
        hits += detect_sudden_large_transfer(df, focus_address)
        hits += detect_similar_value_forwarding(df, focus_address)
        hits += detect_short_time_gap_transfers(df, focus_address)
        hits += detect_service_interactions(df, known_entities)
    hits += translate_clustering_findings(clustering_result, chain)
    return [asdict(h) for h in hits]
