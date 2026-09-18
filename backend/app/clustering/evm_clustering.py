"""
Ethereum / EVM wallet clustering heuristics.

Research basis: Victor, F. (2020), "Address Clustering Heuristics for
Ethereum" -- deposit addresses and exchange-forwarding behavior are the
dominant, reliable clustering signal on account-based chains (unlike
Bitcoin's UTXO co-spend heuristic, which doesn't apply here at all).
This module intentionally does NOT reuse anything from
btc_clustering.py -- see that module's docstring for why chain-specific
heuristics matter (the project brief is explicit about this).

Every cluster returned carries `evidence`: a plain-language, per-finding
explanation, never a bare cluster id -- this feeds directly into the
Attribution / Evidence Engine (app/attribution/vasp_candidate_engine.py).
"""
from collections import defaultdict

import pandas as pd

FORWARD_WINDOW_SECONDS = 3600      # "shortly after" for deposit -> sweep detection
SIMILAR_VALUE_TOLERANCE = 0.03     # 3%: forwarded amount ~= received amount minus network fee
MIN_DEPOSITORS_FOR_SWEEP = 3       # how many distinct depositors before we call it a deposit address


def detect_deposit_addresses(df: pd.DataFrame, focus_address: str) -> list[dict]:
    """
    Deposit-address heuristic: an intermediary wallet W receives from many
    distinct addresses (fan-in) and then forwards consolidated balances
    onward to a small, stable set of destinations shortly after each
    receipt ("sweep"). That destination is very likely an exchange hot
    wallet / custodial deposit-sweep address; W itself is very likely a
    per-user deposit address rather than a personally-owned wallet.
    """
    findings: list[dict] = []
    if df.empty:
        return findings

    # Look at every wallet that appears as a counterparty within this
    # investigation's already-collected data (not the whole chain --
    # that's out of scope for a single-wallet trace).
    candidate_wallets = set(df["from_address"]) | set(df["counterparty"])
    for wallet in candidate_wallets:
        incoming = df[(df["to_address"] == wallet)]
        outgoing = df[(df["from_address"] == wallet)]
        if incoming.empty or outgoing.empty:
            continue

        distinct_depositors = incoming["from_address"].nunique()
        if distinct_depositors < MIN_DEPOSITORS_FOR_SWEEP:
            continue

        sweep_hits = 0
        matched_destinations: set[str] = set()
        for _, deposit in incoming.iterrows():
            window = outgoing[
                (outgoing["timestamp"] >= deposit["timestamp"])
                & (outgoing["timestamp"] <= deposit["timestamp"] + pd.Timedelta(seconds=FORWARD_WINDOW_SECONDS))
            ]
            for _, sweep in window.iterrows():
                if deposit["value"] == 0:
                    continue
                delta = abs(sweep["value"] - deposit["value"]) / deposit["value"]
                if delta <= SIMILAR_VALUE_TOLERANCE * 3:  # looser: sweeps often batch several deposits
                    sweep_hits += 1
                    matched_destinations.add(sweep["to_address"])
                    break

        if sweep_hits >= MIN_DEPOSITORS_FOR_SWEEP and len(matched_destinations) <= 2:
            findings.append(
                {
                    "wallet": wallet,
                    "pattern": "deposit_address_behavior",
                    "distinct_depositors": int(distinct_depositors),
                    "sweep_matches": sweep_hits,
                    "swept_to": list(matched_destinations),
                    "evidence": (
                        f"{wallet} received deposits from {distinct_depositors} distinct addresses and "
                        f"forwarded {sweep_hits} of them onward to {len(matched_destinations)} stable "
                        f"destination(s) within {FORWARD_WINDOW_SECONDS // 60} minutes -- the classic "
                        f"shape of an exchange per-user deposit address, not a personally-held wallet."
                    ),
                    "confidence": "inferred",
                }
            )
    return findings


def detect_shared_destination(df: pd.DataFrame, focus_address: str) -> list[dict]:
    """Multiple otherwise-unrelated wallets in this trace all send to the
    same destination -- weak evidence on its own (could just be a popular
    exchange), but strengthens other evidence when combined."""
    findings = []
    if df.empty:
        return findings
    to_senders: dict[str, set[str]] = defaultdict(set)
    for _, row in df[df["direction"] == "outgoing"].iterrows():
        if row["to_address"]:
            to_senders[row["to_address"]].add(row["from_address"])

    for dest, senders in to_senders.items():
        if len(senders) >= 3:
            findings.append(
                {
                    "wallet": dest,
                    "pattern": "shared_destination_behavior",
                    "distinct_senders": len(senders),
                    "senders": list(senders),
                    "evidence": (
                        f"{len(senders)} distinct wallets observed in this trace all send funds to {dest}, "
                        f"consistent with a shared custodial or service destination."
                    ),
                    "confidence": "observed",
                }
            )
    return findings


def detect_passthrough_wallets(df: pd.DataFrame, focus_address: str) -> list[dict]:
    """A -> W -> B where W forwards almost the exact amount it received,
    almost immediately: classic layering hop, and behavioral evidence
    that W is operated by whoever controls the funds (not an independent
    party), per Victor (2020)'s transaction-behavior-similarity signal."""
    findings = []
    if df.empty:
        return findings
    wallets = set(df["from_address"]) | set(df["counterparty"])
    for wallet in wallets:
        incoming = df[df["to_address"] == wallet].sort_values("timestamp")
        outgoing = df[df["from_address"] == wallet].sort_values("timestamp")
        if incoming.empty or outgoing.empty:
            continue

        # One finding per wallet, not per transaction pair. A wallet that
        # passes funds through 40 times should read as one strong finding
        # with a count, not flood the investigator's pattern list with 40
        # near-identical rows.
        matches: list[dict] = []
        for _, inc in incoming.iterrows():
            nxt = outgoing[outgoing["timestamp"] >= inc["timestamp"]].head(1)
            if nxt.empty or inc["value"] == 0:
                continue
            out_row = nxt.iloc[0]
            gap = (out_row["timestamp"] - inc["timestamp"]).total_seconds()
            similarity = 1 - abs(out_row["value"] - inc["value"]) / inc["value"]
            if gap <= FORWARD_WINDOW_SECONDS and similarity >= (1 - SIMILAR_VALUE_TOLERANCE):
                matches.append(
                    {"inc": inc, "out": out_row, "gap": gap, "similarity": similarity}
                )

        if not matches:
            continue

        best = min(matches, key=lambda m: m["gap"])
        median_gap = sorted(m["gap"] for m in matches)[len(matches) // 2]
        findings.append(
            {
                "wallet": wallet,
                "pattern": "rapid_passthrough",
                "occurrences": len(matches),
                "from": best["inc"]["from_address"],
                "to": best["out"]["to_address"],
                "gap_seconds": best["gap"],
                "median_gap_seconds": median_gap,
                "value_similarity": round(best["similarity"], 4),
                "tx_hashes": [m["inc"]["tx_hash"] for m in matches][:25],
                "evidence": (
                    f"{wallet} forwarded funds onward almost immediately on {len(matches)} occasion(s) "
                    f"(median delay {int(median_gap)}s). Example: received {best['inc']['value']:.6f} "
                    f"{best['inc']['asset']} from {best['inc']['from_address']} and sent "
                    f"{best['out']['value']:.6f} {best['out']['asset']} to {best['out']['to_address']} "
                    f"{int(best['gap'])}s later -- behaves as a pass-through layering hop, not a wallet "
                    f"accumulating funds."
                ),
                "confidence": "inferred",
            }
        )
    return findings


def cluster_evm_wallets(df: pd.DataFrame, focus_address: str) -> dict:
    return {
        "deposit_addresses": detect_deposit_addresses(df, focus_address),
        "shared_destinations": detect_shared_destination(df, focus_address),
        "passthrough_wallets": detect_passthrough_wallets(df, focus_address),
    }
