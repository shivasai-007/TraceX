"""
Normalization / light EDA layer, sitting between raw provider output and
everything else (graph engine, clustering, pattern engine, ML features).

This is deliberately small: dedupe, tag direction relative to the wallet
being investigated, drop obviously-broken rows, and emit both (a) a tidy
list[dict] the rest of the app is built on and (b) a pandas DataFrame for
anything statistical (ml/ feature engineering reuses this exact function).
"""
from dataclasses import asdict

import pandas as pd

from app.ingestion.base import RawTransaction


def normalize_transactions(transactions: list[RawTransaction], focus_address: str) -> list[dict]:
    focus = focus_address.lower()
    seen: set[tuple] = set()
    normalized: list[dict] = []

    for tx in transactions:
        # de-dup: same hash + asset + counterpart can appear twice across
        # txlist/tokentx merges or paginated Bitcoin flattening
        key = (tx.tx_hash, tx.from_address, tx.to_address, tx.asset, round(tx.value, 12))
        if key in seen:
            continue
        seen.add(key)

        if tx.value < 0:  # malformed row guard
            continue

        direction = (
            "outgoing" if tx.from_address.lower() == focus else
            "incoming" if (tx.to_address or "").lower() == focus else
            "unrelated"
        )
        if direction == "unrelated":
            continue

        row = asdict(tx)
        row["direction"] = direction
        row["counterparty"] = (tx.to_address if direction == "outgoing" else tx.from_address) or ""
        row["counterparty"] = row["counterparty"].lower()
        normalized.append(row)

    normalized.sort(key=lambda r: r["timestamp"])
    return normalized


def to_dataframe(normalized_rows: list[dict]) -> pd.DataFrame:
    if not normalized_rows:
        return pd.DataFrame(
            columns=[
                "tx_hash", "block_number", "timestamp", "from_address", "to_address",
                "asset", "value", "fee", "direction", "counterparty",
            ]
        )
    df = pd.DataFrame(normalized_rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.drop(columns=["raw"], errors="ignore")
