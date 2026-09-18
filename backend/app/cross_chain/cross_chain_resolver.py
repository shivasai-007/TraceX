"""
Cross-Chain Resolver.

Per the project's own MVP roadmap, full cross-chain tracing (following
bridged funds onto the destination chain and continuing the trace there)
is explicitly a "later module" -- it needs a bridge-by-bridge mapping of
deposit events to mint/release events, which varies per bridge protocol
and is out of scope for the MVP pipeline this build implements end-to-end.

What IS implemented now (Phase 1, matches the architecture diagram's
Graph Engine -> Cross-Chain Resolver -> Risk Fusion edge): detect when
the investigated wallet interacted with a KNOWN bridge contract, and
surface that as a cross-chain EXIT event -- evidence that funds left the
traced chain, even before we can automatically pick the trace back up on
the destination chain.

Phase 2 extension point: subclass/extend `resolve_bridge_destination`
with a per-bridge-protocol parser (e.g. decode a Wormhole/LayerZero/
Polygon-PoS-bridge event log to get the destination chain + address),
then feed that address back into app.orchestrator.case_orchestrator to
continue the trace automatically.
"""
import pandas as pd


def detect_cross_chain_exits(df: pd.DataFrame, known_entity_matches: dict[str, dict]) -> list[dict]:
    if df.empty:
        return []
    events = []
    for _, row in df.iterrows():
        entity = known_entity_matches.get(row["counterparty"])
        if entity and entity["entity_type"] == "bridge":
            events.append(
                {
                    "tx_hash": row["tx_hash"],
                    "source_chain": row.get("_chain", "unknown"),
                    "bridge_name": entity["name"],
                    "bridge_address": row["counterparty"],
                    "amount": row["value"],
                    "asset": row["asset"],
                    "timestamp": str(row["timestamp"]),
                    "destination_chain": "unresolved",
                    "note": (
                        "Funds exited via a known bridge contract. Automatic destination-chain "
                        "resolution is a documented Phase 2 extension point (per-bridge event "
                        "decoding) -- see this module's docstring."
                    ),
                }
            )
    return events
