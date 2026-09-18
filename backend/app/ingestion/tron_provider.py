"""
TRON is registered in the architecture (it appears in the Ingestion Plane
of the Lucid diagram, and TRC-20 USDT is one of the most common rails in
South/Southeast Asian pig-butchering and romance-scam cash-out chains) but
is deliberately left unimplemented in this build -- the project brief
asks to keep live integrations to Etherscan + Bitcoin only, and the
project's own MVP roadmap defers non-Ethereum chains until the core
VASP-attribution pipeline is proven out.

To implement it later: TRON is not EVM-compatible, so it needs its own
adapter (TronGrid or a similar TRON full-node API), not the Etherscan v2
provider. Follow the same ChainProvider contract as evm_provider.py /
bitcoin_provider.py -- that is the whole point of the provider registry.
"""
from app.ingestion.base import ProviderNotImplemented


def build_tron_provider() -> ProviderNotImplemented:
    return ProviderNotImplemented("tron")
