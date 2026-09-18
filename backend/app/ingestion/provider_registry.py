"""
Provider Registry: one place that maps a chain name to its adapter.
Everything downstream (orchestrator, workers) asks this registry for a
provider instead of importing a specific adapter -- that's what lets a
new chain be added without touching the rest of the pipeline.
"""
from app.ingestion.base import ChainProvider
from app.ingestion.bitcoin_provider import BitcoinProvider
from app.ingestion.evm_provider import EVMProvider
from app.ingestion.tron_provider import build_tron_provider

_EVM_CHAINS = {"ethereum", "polygon"}


def get_provider(chain: str) -> ChainProvider:
    chain = chain.lower()
    if chain in _EVM_CHAINS:
        return EVMProvider(chain)
    if chain == "bitcoin":
        return BitcoinProvider()
    if chain == "tron":
        return build_tron_provider()
    raise ValueError(f"Unsupported chain: {chain}")


def supported_chains() -> list[str]:
    return ["ethereum", "polygon", "bitcoin", "tron"]


def live_chains() -> list[str]:
    """Chains with a real, working adapter today (vs. registered-only)."""
    return ["ethereum", "polygon", "bitcoin"]
