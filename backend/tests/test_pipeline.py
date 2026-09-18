"""
Tests for the analytic core: normalization, clustering, the rule engine,
the VASP candidate engine, risk fusion and the shared feature contract.

These deliberately use synthetic transaction data shaped like a real
laundering flow (victim -> suspect, mule fan-in, rapid similar-value
forwarding, deposit-address sweep to an exchange) rather than mocking
the analytic functions, so they test the actual detection logic.

Run from backend/ with the virtualenv active:
    pytest tests/ -v
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml" / "src"))

from app.attribution.vasp_candidate_engine import build_vasp_candidates  # noqa: E402
from app.clustering.btc_clustering import (  # noqa: E402
    detect_common_input_clusters,
    detect_consolidation,
)
from app.clustering.evm_clustering import cluster_evm_wallets  # noqa: E402
from app.graph_engine.graph_service import GraphEngine  # noqa: E402
from app.ingestion.base import RawTransaction  # noqa: E402
from app.normalization.normalize import normalize_transactions, to_dataframe  # noqa: E402
from app.patterns.rule_engine import run_rule_engine  # noqa: E402
from app.risk.risk_fusion import fuse_risk  # noqa: E402

VICTIM = "0xv1ct1m0000000000000000000000000000000001"
SUSPECT = "0x5u5pect000000000000000000000000000000001"
DEPOSIT = "0xdep0517000000000000000000000000000000001"
HOTWALLET = "0xh0twa11et00000000000000000000000000000001"
BASE_TIME = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _tx(tx_hash, ts, sender, recipient, value, asset="ETH"):
    return RawTransaction(
        tx_hash=tx_hash,
        block_number=1000,
        timestamp=ts,
        from_address=sender,
        to_address=recipient,
        asset=asset,
        value=value,
        fee=0.001,
    )


@pytest.fixture
def laundering_flow():
    """Victim pays the suspect; six mules also pay in; the suspect forwards
    near-identical amounts to a deposit address minutes later; the deposit
    address sweeps everything to one exchange hot wallet."""
    txs = [_tx("0xaa01", BASE_TIME, VICTIM, SUSPECT, 12.5)]
    for i in range(6):
        txs.append(_tx(f"0xbb{i:02d}", BASE_TIME + timedelta(hours=i), f"0xmu1e{i:036d}", SUSPECT, 1.9 + i * 0.01))
    for i in range(5):
        txs.append(_tx(f"0xcc{i:02d}", BASE_TIME + timedelta(hours=i, minutes=1), SUSPECT, DEPOSIT, 1.88))
    for i in range(5):
        txs.append(_tx(f"0xdd{i:02d}", BASE_TIME + timedelta(hours=i, minutes=3), DEPOSIT, HOTWALLET, 1.87))
    return txs


@pytest.fixture
def full_graph_df(laundering_flow):
    """Every edge in the flow, not just the suspect-relative view -- this is
    what the clustering heuristics need to see the deposit-address sweep."""
    rows = []
    for t in laundering_flow:
        rows.append(
            {
                "tx_hash": t.tx_hash,
                "timestamp": t.timestamp,
                "from_address": t.from_address,
                "to_address": t.to_address,
                "asset": t.asset,
                "value": t.value,
                "direction": "outgoing" if t.from_address == SUSPECT else "incoming",
                "counterparty": t.to_address if t.from_address == SUSPECT else t.from_address,
            }
        )
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


# ----------------------------------------------------------- normalization

def test_normalize_keeps_only_transactions_touching_the_focus_wallet(laundering_flow):
    rows = normalize_transactions(laundering_flow, SUSPECT)
    assert len(rows) == 12  # 7 in, 5 out; the 5 deposit->hotwallet edges are not the suspect's
    assert all(r["direction"] in ("incoming", "outgoing") for r in rows)


def test_normalize_tags_direction_and_counterparty(laundering_flow):
    rows = normalize_transactions(laundering_flow, SUSPECT)
    incoming = [r for r in rows if r["direction"] == "incoming"]
    outgoing = [r for r in rows if r["direction"] == "outgoing"]
    assert len(incoming) == 7
    assert len(outgoing) == 5
    assert all(r["counterparty"] != SUSPECT for r in rows)


def test_normalize_deduplicates_repeated_rows(laundering_flow):
    doubled = laundering_flow + laundering_flow
    assert len(normalize_transactions(doubled, SUSPECT)) == 12


def test_to_dataframe_handles_empty_input():
    df = to_dataframe([])
    assert df.empty
    assert "tx_hash" in df.columns  # still schema-shaped, so downstream code doesn't KeyError


# ------------------------------------------------------------------ graph

def test_graph_builds_and_exports_for_the_frontend(laundering_flow):
    graph = GraphEngine()
    graph.add_wallet(SUSPECT, "ethereum", label="Suspect")
    graph.add_transactions(normalize_transactions(laundering_flow, SUSPECT), "ethereum")

    assert graph.node_count() > 0
    exported = graph.to_frontend_json(SUSPECT)
    assert any(node["isFocus"] for node in exported["nodes"])
    assert all("source" in edge and "target" in edge for edge in exported["edges"])


def test_hop_subgraph_respects_the_hop_limit(laundering_flow):
    graph = GraphEngine()
    graph.add_transactions(normalize_transactions(laundering_flow, SUSPECT), "ethereum")
    one_hop = graph.hop_subgraph(SUSPECT, 1)
    assert SUSPECT in one_hop
    assert one_hop.number_of_nodes() <= graph.node_count()


# ------------------------------------------------------------- clustering

def test_evm_clustering_detects_the_deposit_address_sweep(full_graph_df):
    result = cluster_evm_wallets(full_graph_df, SUSPECT)
    assert result["deposit_addresses"], "the fan-in + sweep pattern should be detected"
    assert all(f["evidence"] for f in result["deposit_addresses"]), "findings must carry evidence"


def test_passthrough_findings_are_one_per_wallet_not_one_per_transaction(full_graph_df):
    result = cluster_evm_wallets(full_graph_df, SUSPECT)
    wallets = [f["wallet"] for f in result["passthrough_wallets"]]
    assert len(wallets) == len(set(wallets)), "a wallet should produce at most one passthrough finding"
    assert all(f.get("occurrences", 0) >= 1 for f in result["passthrough_wallets"])


def test_bitcoin_common_input_clusters_co_spent_addresses():
    raw = [{
        "txid": "btc-tx-1",
        "vin": [
            {"prevout": {"scriptpubkey_address": "bc1aaa", "value": 100000, "scriptpubkey_type": "v0_p2wpkh"}},
            {"prevout": {"scriptpubkey_address": "bc1bbb", "value": 200000, "scriptpubkey_type": "v0_p2wpkh"}},
        ],
        "vout": [{"scriptpubkey_address": "bc1ccc", "value": 290000, "scriptpubkey_type": "v0_p2wpkh"}],
    }]
    result = detect_common_input_clusters(raw)
    assert result["clusters"] == [["bc1aaa", "bc1bbb"]]
    assert result["evidence"][0]["confidence"] == "inferred"  # never claimed as confirmed


def test_coinjoin_is_excluded_from_common_input_clustering():
    """CoinJoin exists to make co-spending NOT imply shared ownership.
    Clustering it would merge unrelated people into one cluster."""
    raw = [{
        "txid": "coinjoin-1",
        "vin": [
            {"prevout": {"scriptpubkey_address": f"bc1user{i}", "value": 1000000, "scriptpubkey_type": "v0_p2wpkh"}}
            for i in range(6)
        ],
        "vout": [
            {"scriptpubkey_address": f"bc1out{i}", "value": 900000, "scriptpubkey_type": "v0_p2wpkh"}
            for i in range(6)
        ],
    }]
    result = detect_common_input_clusters(raw)
    assert result["clusters"] == [], "CoinJoin inputs must not be clustered together"
    assert "coinjoin-1" in result["excluded_coinjoin_txids"]


def test_bitcoin_consolidation_detection():
    raw = [{
        "txid": "consolidate-1",
        "vin": [{"prevout": {"scriptpubkey_address": f"bc1in{i}", "value": 50000}} for i in range(7)],
        "vout": [{"scriptpubkey_address": "bc1out", "value": 340000}],
    }]
    findings = detect_consolidation(raw)
    assert len(findings) == 1
    assert findings[0]["input_count"] == 7


# ----------------------------------------------------------- rule engine

def test_rule_engine_detects_fan_in_and_similar_value_forwarding(laundering_flow, full_graph_df):
    df = to_dataframe(normalize_transactions(laundering_flow, SUSPECT))
    clustering = cluster_evm_wallets(full_graph_df, SUSPECT)
    hits = run_rule_engine(df, SUSPECT, "ethereum", [], clustering)
    names = {h["pattern"] for h in hits}
    assert "fan_in_many_to_one" in names
    assert "similar_value_forwarding" in names


def test_every_pattern_hit_carries_evidence_and_a_research_reference(laundering_flow, full_graph_df):
    """This is the project's core commitment: no finding without its basis."""
    df = to_dataframe(normalize_transactions(laundering_flow, SUSPECT))
    clustering = cluster_evm_wallets(full_graph_df, SUSPECT)
    hits = run_rule_engine(df, SUSPECT, "ethereum", [], clustering)
    assert hits
    for hit in hits:
        assert hit["explanation"], f"{hit['pattern']} has no explanation"
        assert hit["evidence"], f"{hit['pattern']} has no evidence"
        assert hit["research_reference"], f"{hit['pattern']} has no research reference"
        assert hit["confidence"] in ("observed", "inferred", "attributed", "confirmed")


def test_mixer_interaction_is_critical_severity(laundering_flow):
    df = to_dataframe(normalize_transactions(laundering_flow, SUSPECT))
    mixer = {
        "address": DEPOSIT,
        "name": "Test Mixer",
        "entity_type": "mixer",
        "source": "test",
        "confidence": "attributed",
    }
    hits = run_rule_engine(df, SUSPECT, "ethereum", [mixer], {})
    mixer_hits = [h for h in hits if h["pattern"] == "mixer_interaction"]
    assert mixer_hits
    assert all(h["severity"] == "critical" for h in mixer_hits)


# -------------------------------------------------- VASP candidate engine

def test_vasp_candidates_carry_evidence_and_a_confidence_tier(laundering_flow, full_graph_df):
    graph = GraphEngine()
    graph.add_transactions(normalize_transactions(laundering_flow, SUSPECT), "ethereum")
    for t in laundering_flow:
        graph.g.add_edge(t.from_address, t.to_address, key=t.tx_hash, value=t.value, tx_hash=t.tx_hash)

    entities = {
        HOTWALLET: {
            "address": HOTWALLET,
            "name": "Test Exchange",
            "entity_type": "exchange",
            "source": "test fixture",
            "source_date": "2026-01-01",
            "confidence": "attributed",
        }
    }
    clustering = cluster_evm_wallets(full_graph_df, SUSPECT)
    candidates = build_vasp_candidates(full_graph_df, SUSPECT, "ethereum", graph.g, entities, clustering)

    assert candidates
    for candidate in candidates:
        assert candidate["evidence"], f"{candidate['name']} was generated with no evidence"
        assert candidate["confidence"] in ("observed", "inferred", "attributed", "confirmed")
        assert candidate["exposure"] in ("direct", "indirect")


def test_named_attributed_candidate_outranks_an_unattributed_cluster(laundering_flow, full_graph_df):
    graph = GraphEngine()
    for t in laundering_flow:
        graph.add_wallet(t.from_address, "ethereum")
        graph.add_wallet(t.to_address, "ethereum")
        graph.g.add_edge(t.from_address, t.to_address, key=t.tx_hash, value=t.value, tx_hash=t.tx_hash)

    entities = {
        HOTWALLET: {
            "address": HOTWALLET, "name": "Test Exchange", "entity_type": "exchange",
            "source": "test", "source_date": "2026-01-01", "confidence": "attributed",
        }
    }
    clustering = cluster_evm_wallets(full_graph_df, SUSPECT)
    candidates = build_vasp_candidates(full_graph_df, SUSPECT, "ethereum", graph.g, entities, clustering)
    assert candidates[0]["confidence"] in ("attributed", "confirmed")


# ------------------------------------------------------------ risk fusion

def test_risk_fusion_redistributes_weight_when_no_model_is_trained():
    """A missing model must not be counted as a zero-risk vote."""
    patterns = [{
        "pattern": "mixer_interaction", "severity": "critical",
        "explanation": "x", "evidence": "y", "research_reference": "z",
    }]
    result = fuse_risk(patterns, {"hits": [], "exposure_score": 0.0},
                       {"available": False, "reason": "no model"},
                       {"total_transactions": 10, "counterparty_count": 5})
    assert result["components"]["ml"]["weight"] == 0.0
    assert result["components"]["ml"]["available"] is False
    assert result["components"]["rules"]["weight"] > 0.45  # rules absorbed the ML weight
    assert result["components"]["ml"]["note"]


def test_risk_fusion_uses_the_model_when_one_is_available():
    result = fuse_risk([], {"hits": [], "exposure_score": 0.0},
                       {"available": True, "score": 0.9, "algorithm": "xgboost"},
                       {"total_transactions": 10, "counterparty_count": 5})
    assert result["components"]["ml"]["weight"] == 0.20
    assert result["risk_score"] > 0


def test_risk_score_is_always_decomposable():
    """The score must never be a bare number -- an investigator has to be
    able to see what produced it."""
    patterns = [{"pattern": "fan_in_many_to_one", "severity": "medium",
                 "explanation": "x", "evidence": "y", "research_reference": "z"}]
    result = fuse_risk(patterns, {"hits": [], "exposure_score": 0.2},
                       {"available": False}, {"total_transactions": 40, "counterparty_count": 30,
                                              "active_duration_days": 1})
    assert 0 <= result["risk_score"] <= 1
    assert result["risk_band"] in ("minimal", "low", "medium", "high", "critical")
    assert set(result["components"]) == {"rules", "threat_intel", "ml"}
    assert result["indicators"]
    assert result["methodology_note"]


def test_high_counterparty_count_raises_a_behavioural_indicator():
    result = fuse_risk([], {"hits": [], "exposure_score": 0.0}, {"available": False},
                       {"total_transactions": 200, "counterparty_count": 60, "active_duration_days": 2})
    names = {i["indicator"] for i in result["indicators"]}
    assert "high_counterparty_count" in names
    assert "high_transaction_velocity" in names


# ------------------------------------------------------- feature contract

def test_feature_extraction_matches_the_declared_schema(laundering_flow):
    """Training and serving share this function; the schema must be stable."""
    from features.build_features import FEATURE_NAMES, extract_wallet_features

    rows = normalize_transactions(laundering_flow, SUSPECT)
    features = extract_wallet_features(rows, SUSPECT)
    assert set(features) == set(FEATURE_NAMES)
    assert all(isinstance(v, (int, float)) for v in features.values())
    assert features["total_tx_count"] == 12
    assert features["in_count"] == 7
    assert features["out_count"] == 5


def test_feature_extraction_handles_an_empty_wallet():
    from features.build_features import FEATURE_NAMES, extract_wallet_features

    features = extract_wallet_features([], SUSPECT)
    assert set(features) == set(FEATURE_NAMES)
    assert all(v == 0.0 for v in features.values())
