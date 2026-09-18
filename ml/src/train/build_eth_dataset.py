"""
Build a native-schema Ethereum training set from labeled addresses.

    python src/train/build_eth_dataset.py --labels data/raw/eth_labels.csv

This is the highest-quality path to a model, because it produces exactly
the feature schema the live pipeline computes (100% coverage, zero
train/serve skew) -- unlike the public Bitcoin datasets, whose columns
have to be mapped approximately onto the schema.

INPUT: a CSV with two columns:
    address,label
    0xabc...,1        <- 1 = known illicit (phishing/scam/fraud)
    0xdef...,0        <- 0 = known benign

Where to get labeled addresses is covered in ml/DATASET.md. In short:
Etherscan's own phish/hack address tags, CryptoScamDB and Chainabuse
exports for the positive class; high-activity addresses with no adverse
tags (or your own verified-benign list) for the negative class.

OUTPUT: data/raw/eth_wallet_features.csv, ready for:
    python src/train/train_baseline.py --dataset eth-phishing --model xgboost

Note this script makes one Etherscan API call per address (two, counting
token transfers), so it is rate-limited on purpose. A few thousand
labeled addresses on the free tier takes a while -- start it and leave it.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import pandas as pd

# Reuse the backend's real ingestion + normalization code so the training
# features are produced by exactly the same path as the serving features.
BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.build_features import FEATURE_NAMES, extract_wallet_features  # noqa: E402


async def _collect_one(address: str, chain: str):
    from app.ingestion.provider_registry import get_provider
    from app.normalization.normalize import normalize_transactions

    provider = get_provider(chain)
    txs = await provider.get_transactions(address, limit=2000)
    return normalize_transactions(txs, address)


async def build(labels_df: pd.DataFrame, chain: str, delay: float) -> pd.DataFrame:
    rows = []
    total = len(labels_df)
    for i, record in enumerate(labels_df.itertuples(index=False), 1):
        address = str(record.address).strip().lower()
        label = int(record.label)
        try:
            normalized = await _collect_one(address, chain)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}/{total}] {address[:12]}... FAILED: {exc}")
            continue

        if not normalized:
            print(f"  [{i}/{total}] {address[:12]}... no transactions, skipped")
            continue

        features = extract_wallet_features(normalized, address)
        features["address"] = address
        features["label"] = label
        rows.append(features)
        print(f"  [{i}/{total}] {address[:12]}... {len(normalized)} tx, label={label}")
        time.sleep(delay)  # stay inside the free-tier rate limit

    return pd.DataFrame(rows, columns=FEATURE_NAMES + ["address", "label"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an Ethereum wallet feature dataset from labeled addresses.")
    parser.add_argument("--labels", type=Path, required=True, help="CSV with columns: address,label")
    parser.add_argument("--chain", default="ethereum", choices=["ethereum", "polygon"])
    parser.add_argument("--delay", type=float, default=0.25, help="Seconds between API calls (free tier: keep >= 0.2)")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "data" / "raw" / "eth_wallet_features.csv")
    args = parser.parse_args()

    if not args.labels.exists():
        raise SystemExit(f"Labels file not found: {args.labels}\nSee ml/DATASET.md for how to assemble one.")

    labels_df = pd.read_csv(args.labels)
    missing = {"address", "label"} - set(labels_df.columns)
    if missing:
        raise SystemExit(f"Labels CSV is missing column(s): {', '.join(missing)}. Expected: address,label")

    print(f"Building features for {len(labels_df):,} labeled addresses on {args.chain}...")
    print("(This calls Etherscan once per address -- ETHERSCAN_API_KEY must be set in backend/.env)")
    df = asyncio.run(build(labels_df, args.chain, args.delay))

    if df.empty:
        raise SystemExit("No features were built. Check your API key and the addresses in the labels file.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"\nWrote {len(df):,} rows -> {args.out}")
    print(f"Class balance: {df['label'].mean():.2%} positive")
    print("\nNext: python src/train/train_baseline.py --dataset eth-phishing --model xgboost --split random")


if __name__ == "__main__":
    main()
