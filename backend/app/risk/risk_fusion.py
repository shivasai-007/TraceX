"""
Risk Fusion (the architecture diagram's central red block).

The brief is explicit: "Do not make this only one ML prediction."
So the risk result is a FUSION of three independently-inspectable signals,
each of which an investigator can see and argue with separately:

  1. Rule indicators   -- from the Topology/Rule Engine (FATF red flags,
                          fan-in/out, structuring, layering, mixer hits)
  2. Threat exposure   -- from the Threat Intelligence service (known
                          scam/ransomware/mixer address matches)
  3. ML score          -- from the trained model, IF one is loaded

The output always reports which components actually contributed, so a
score of 0.71 never means "the AI said so" -- it decomposes into named
indicators with weights. When no ML model is trained yet, the fusion
runs on rules + threat intel alone and says so explicitly.
"""
from __future__ import annotations

SEVERITY_WEIGHT = {"info": 0.0, "low": 0.1, "medium": 0.25, "high": 0.5, "critical": 0.9}

# Fusion weights. Rules carry the most weight because they are the component
# an investigator can defend in a report line-by-line; the ML score is a
# prioritization aid, not the verdict.
W_RULES = 0.45
W_THREAT = 0.35
W_ML = 0.20


def _rule_component(patterns: list[dict]) -> tuple[float, list[dict]]:
    if not patterns:
        return 0.0, []
    indicators = []
    total = 0.0
    for p in patterns:
        weight = SEVERITY_WEIGHT.get(p.get("severity", "low"), 0.1)
        total += weight
        indicators.append(
            {
                "indicator": p["pattern"],
                "severity": p.get("severity", "low"),
                "weight": weight,
                "explanation": p.get("explanation", ""),
                "evidence": p.get("evidence", ""),
                "research_reference": p.get("research_reference", ""),
            }
        )
    # saturating: 4 critical-equivalent findings reach the ceiling
    score = min(1.0, total / 3.6)
    return round(score, 4), indicators


def _derive_behavioral_indicators(summary: dict, patterns: list[dict]) -> list[dict]:
    """Indicators the brief names explicitly that aren't already rule hits:
    high transaction velocity, high counterparty count, exposure flags."""
    indicators = []
    tx_count = summary.get("total_transactions", 0)
    counterparties = summary.get("counterparty_count", 0)
    duration_days = summary.get("active_duration_days") or 0

    if duration_days and tx_count / max(duration_days, 1) > 20:
        indicators.append(
            {
                "indicator": "high_transaction_velocity",
                "severity": "medium",
                "weight": SEVERITY_WEIGHT["medium"],
                "explanation": f"{tx_count} transactions over {duration_days:.1f} active days.",
                "evidence": f"Averages {tx_count / max(duration_days, 1):.1f} transactions per active day.",
                "research_reference": "FATF (2020), Virtual Assets Red Flag Indicators",
            }
        )
    if counterparties >= 25:
        indicators.append(
            {
                "indicator": "high_counterparty_count",
                "severity": "medium",
                "weight": SEVERITY_WEIGHT["medium"],
                "explanation": f"Wallet interacted with {counterparties} distinct addresses.",
                "evidence": f"{counterparties} unique counterparties observed in the collected trace.",
                "research_reference": "FATF (2020), Virtual Assets Red Flag Indicators",
            }
        )

    pattern_names = {p["pattern"] for p in patterns}
    for name, label in (
        ("mixer_interaction", "mixer_exposure"),
        ("bridge_interaction", "bridge_exposure"),
        ("dex_interaction", "dex_exposure"),
    ):
        if name in pattern_names:
            indicators.append(
                {
                    "indicator": label,
                    "severity": "high" if label != "dex_exposure" else "medium",
                    "weight": SEVERITY_WEIGHT["high" if label != "dex_exposure" else "medium"],
                    "explanation": f"Trace shows {label.replace('_', ' ')}.",
                    "evidence": f"At least one transaction matched the {name} rule.",
                    "research_reference": "FATF (2020), Virtual Assets Red Flag Indicators",
                }
            )
    return indicators


def fuse_risk(
    patterns: list[dict],
    threat_result: dict,
    ml_result: dict,
    summary: dict,
) -> dict:
    rule_score, rule_indicators = _rule_component(patterns)
    behavioral = _derive_behavioral_indicators(summary, patterns)
    threat_score = float(threat_result.get("exposure_score", 0.0))
    ml_available = bool(ml_result.get("available"))
    ml_score = float(ml_result.get("score") or 0.0)

    if ml_available:
        weights = {"rules": W_RULES, "threat": W_THREAT, "ml": W_ML}
        fused = rule_score * W_RULES + threat_score * W_THREAT + ml_score * W_ML
    else:
        # redistribute the ML weight proportionally across the two available
        # components rather than treating a missing model as a zero-risk vote
        total = W_RULES + W_THREAT
        weights = {"rules": W_RULES / total, "threat": W_THREAT / total, "ml": 0.0}
        fused = rule_score * weights["rules"] + threat_score * weights["threat"]

    fused = round(min(1.0, fused), 4)
    band = (
        "critical" if fused >= 0.8
        else "high" if fused >= 0.6
        else "medium" if fused >= 0.35
        else "low" if fused >= 0.15
        else "minimal"
    )

    return {
        "risk_score": fused,
        "risk_band": band,
        "components": {
            "rules": {"score": rule_score, "weight": round(weights["rules"], 3), "indicator_count": len(rule_indicators)},
            "threat_intel": {"score": round(threat_score, 4), "weight": round(weights["threat"], 3), "hits": threat_result.get("hits", [])},
            "ml": {
                "score": ml_result.get("score"),
                "weight": round(weights["ml"], 3),
                "available": ml_available,
                "note": ml_result.get("reason") if not ml_available else None,
                "algorithm": ml_result.get("algorithm"),
                "top_features": ml_result.get("top_features", []),
            },
        },
        "indicators": rule_indicators + behavioral,
        "methodology_note": (
            "Risk is a weighted fusion of rule-based FATF/red-flag indicators, known-address threat "
            "intelligence, and (when trained) an ML behavioral score. Each component is reported "
            "separately above so the score can be audited rather than trusted."
        ),
    }
