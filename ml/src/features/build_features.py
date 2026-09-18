"""
THE feature contract between offline training and live inference.

extract_wallet_features() is imported by BOTH:
  - ml/src/train/train_baseline.py            (training, on historical/labeled data)
  - backend/app/risk/ml_inference.py           (serving, on a live trace)
via sys.path wiring documented in ml/MODEL_TRAINING.md and backend's
risk/ml_inference.py -- there is exactly one definition of "what a
feature means" in this project, on purpose: a model that was trained on
one feature schema and served with a silently-different one is a classic,
hard-to-notice way a fraud model goes quietly wrong in production.

Input: a list of normalized transaction dicts (the exact shape produced
by backend/app/normalization/normalize.py::normalize_transactions), all
already relative to one focus wallet, with a "direction" key of
"incoming" | "outgoing".

Output: a flat dict of numeric features -- safe to build a pandas
DataFrame row from directly.

These are deliberately chain-agnostic, wallet-behavior features (not
raw on-chain values) so the same model, and the same code path, works
whether the rows came from Ethereum, Polygon or Bitcoin.
"""
from __future__ import annotations

import math
from datetime import datetime

FEATURE_NAMES = [
    "total_tx_count",
    "in_count",
    "out_count",
    "in_out_ratio",
    "total_in_value",
    "total_out_value",
    "net_flow",
    "mean_value",
    "std_value",
    "max_value",
    "max_value_share",
    "unique_counterparties",
    "in_counterparty_count",
    "out_counterparty_count",
    "counterparty_reuse_ratio",
    "active_duration_days",
    "tx_velocity_per_day",
    "mean_time_gap_seconds",
    "std_time_gap_seconds",
    "asset_diversity",
]


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def extract_wallet_features(rows: list[dict], focus_address: str) -> dict:
    if not rows:
        return {name: 0.0 for name in FEATURE_NAMES}

    focus = focus_address.lower()
    values = [float(r["value"]) for r in rows]
    incoming = [r for r in rows if r["direction"] == "incoming"]
    outgoing = [r for r in rows if r["direction"] == "outgoing"]
    timestamps = sorted(_as_datetime(r["timestamp"]) for r in rows)

    total_in = sum(float(r["value"]) for r in incoming)
    total_out = sum(float(r["value"]) for r in outgoing)
    counterparties = {r["counterparty"] for r in rows if r.get("counterparty")}
    in_counterparties = {r["counterparty"] for r in incoming if r.get("counterparty")}
    out_counterparties = {r["counterparty"] for r in outgoing if r.get("counterparty")}

    gaps = [
        (timestamps[i] - timestamps[i - 1]).total_seconds()
        for i in range(1, len(timestamps))
    ]

    duration_days = (
        (timestamps[-1] - timestamps[0]).total_seconds() / 86400 if len(timestamps) > 1 else 0.0
    )
    mean_value = sum(values) / len(values)
    variance = sum((v - mean_value) ** 2 for v in values) / len(values)

    return {
        "total_tx_count": len(rows),
        "in_count": len(incoming),
        "out_count": len(outgoing),
        "in_out_ratio": (len(incoming) / len(outgoing)) if outgoing else float(len(incoming)),
        "total_in_value": total_in,
        "total_out_value": total_out,
        "net_flow": total_in - total_out,
        "mean_value": mean_value,
        "std_value": math.sqrt(variance),
        "max_value": max(values),
        "max_value_share": (max(values) / sum(values)) if sum(values) else 0.0,
        "unique_counterparties": len(counterparties),
        "in_counterparty_count": len(in_counterparties),
        "out_counterparty_count": len(out_counterparties),
        "counterparty_reuse_ratio": (
            1 - (len(counterparties) / len(rows)) if rows else 0.0
        ),
        "active_duration_days": duration_days,
        "tx_velocity_per_day": (len(rows) / duration_days) if duration_days > 0 else float(len(rows)),
        "mean_time_gap_seconds": (sum(gaps) / len(gaps)) if gaps else 0.0,
        "std_time_gap_seconds": (
            math.sqrt(sum((g - (sum(gaps) / len(gaps))) ** 2 for g in gaps) / len(gaps)) if gaps else 0.0
        ),
        "asset_diversity": len({r.get("asset") for r in rows}),
    }
