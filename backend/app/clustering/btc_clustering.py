"""
Bitcoin (UTXO) clustering heuristics.

Deliberately a SEPARATE module from evm_clustering.py, with different
algorithms, per the project brief: "Do NOT assume the same clustering
algorithm works for every blockchain." Ethereum's deposit-address /
sweep behavior has no UTXO equivalent, and Bitcoin's common-input
heuristic has no meaning on an account-based chain like Ethereum.

Heuristics implemented:
  - Common-input-ownership: addresses spent together as inputs of the
    same transaction are (almost always) controlled by one entity --
    the foundational Bitcoin clustering heuristic (Meiklejohn et al.,
    2013 and every clustering system since).
  - CoinJoin / mixer exception: common-input-ownership BREAKS on
    CoinJoin-style transactions (many inputs, many equal-value outputs,
    contributed by *different, unrelated* people on purpose) -- we
    detect and EXCLUDE these from clustering rather than silently
    mis-clustering unrelated users together, and instead flag the
    transaction as mixer/tumbler interaction for the pattern engine.
  - Change-address heuristic (script-type continuity): a light,
    explicitly-caveated heuristic -- real systems use several combined
    signals (address reuse, round-number outputs, wallet fingerprinting);
    we use the one signal computable from a single transaction's data
    (Esplora already returns each input/output's script type) so this
    stays honest about being one weak signal, not a verdict.
  - Consolidation behavior: many UTXOs swept into one output, common
    right before a cash-out or before entering a mixer.
"""
from collections import defaultdict

COINJOIN_MIN_INPUTS = 5
COINJOIN_MIN_EQUAL_OUTPUTS = 3
CONSOLIDATION_MIN_INPUTS = 5


class _UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _is_likely_coinjoin(raw_tx: dict) -> bool:
    vin, vout = raw_tx.get("vin", []), raw_tx.get("vout", [])
    if len(vin) < COINJOIN_MIN_INPUTS:
        return False
    values = [o.get("value") for o in vout if o.get("value") is not None]
    counts = defaultdict(int)
    for v in values:
        counts[v] += 1
    equal_output_groups = [v for v, c in counts.items() if c >= COINJOIN_MIN_EQUAL_OUTPUTS]
    distinct_input_owners = {
        v.get("prevout", {}).get("scriptpubkey_address") for v in vin if v.get("prevout")
    }
    return bool(equal_output_groups) and len(distinct_input_owners) >= COINJOIN_MIN_INPUTS


def detect_common_input_clusters(raw_txs: list[dict]) -> dict:
    """Returns {"clusters": [[addr, addr, ...], ...], "evidence": [...],
    "excluded_coinjoin_txids": [...]}"""
    uf = _UnionFind()
    evidence = []
    excluded = []

    for tx in raw_txs:
        vin = tx.get("vin", [])
        input_addrs = [v.get("prevout", {}).get("scriptpubkey_address") for v in vin if v.get("prevout")]
        input_addrs = [a for a in input_addrs if a]
        if len(input_addrs) < 2:
            continue
        if _is_likely_coinjoin(tx):
            excluded.append(tx.get("txid"))
            continue
        for a in input_addrs[1:]:
            uf.union(input_addrs[0], a)
        evidence.append(
            {
                "tx_hash": tx.get("txid"),
                "addresses": sorted(set(input_addrs)),
                "evidence": (
                    f"{len(set(input_addrs))} addresses were used as joint inputs to spend the same "
                    f"transaction ({tx.get('txid')}) -- under the common-input-ownership heuristic, "
                    f"UTXOs spent together in one transaction require signatures from all of them, "
                    f"implying a single controlling entity."
                ),
                "confidence": "inferred",
            }
        )

    groups: dict[str, set[str]] = defaultdict(set)
    for addr in uf.parent:
        groups[uf.find(addr)].add(addr)
    clusters = [sorted(g) for g in groups.values() if len(g) > 1]

    return {"clusters": clusters, "evidence": evidence, "excluded_coinjoin_txids": excluded}


def detect_likely_change_outputs(raw_txs: list[dict]) -> list[dict]:
    findings = []
    for tx in raw_txs:
        vin, vout = tx.get("vin", []), tx.get("vout", [])
        if len(vout) != 2 or len(vin) == 0:
            continue
        input_types = [v.get("prevout", {}).get("scriptpubkey_type") for v in vin if v.get("prevout")]
        if not input_types:
            continue
        majority_type = max(set(input_types), key=input_types.count)
        matching = [o for o in vout if o.get("scriptpubkey_type") == majority_type]
        non_matching = [o for o in vout if o.get("scriptpubkey_type") != majority_type]
        if len(matching) == 1 and len(non_matching) == 1:
            findings.append(
                {
                    "tx_hash": tx.get("txid"),
                    "likely_change_address": matching[0].get("scriptpubkey_address"),
                    "likely_payment_address": non_matching[0].get("scriptpubkey_address"),
                    "evidence": (
                        f"In tx {tx.get('txid')}, one output matches the input wallet's script type "
                        f"({majority_type}) and the other does not -- weak evidence the matching output "
                        f"is change returning to the sender, and the other is the actual payment. "
                        f"Caveat: script-type continuity alone has known false positives; treat as one "
                        f"signal, not a conclusion."
                    ),
                    "confidence": "inferred",
                }
            )
    return findings


def detect_consolidation(raw_txs: list[dict]) -> list[dict]:
    findings = []
    for tx in raw_txs:
        vin, vout = tx.get("vin", []), tx.get("vout", [])
        if len(vin) >= CONSOLIDATION_MIN_INPUTS and len(vout) == 1:
            findings.append(
                {
                    "tx_hash": tx.get("txid"),
                    "input_count": len(vin),
                    "evidence": (
                        f"{len(vin)} separate UTXOs were consolidated into a single output in tx "
                        f"{tx.get('txid')} -- consistent with deliberate fund consolidation, often seen "
                        f"shortly before a cash-out or mixer deposit."
                    ),
                    "confidence": "observed",
                }
            )
    return findings


def cluster_btc_wallets(raw_txs: list[dict]) -> dict:
    common_input = detect_common_input_clusters(raw_txs)
    return {
        "common_input_clusters": common_input["clusters"],
        "common_input_evidence": common_input["evidence"],
        "excluded_coinjoin_txids": common_input["excluded_coinjoin_txids"],
        "likely_change_outputs": detect_likely_change_outputs(raw_txs),
        "consolidation_events": detect_consolidation(raw_txs),
    }
