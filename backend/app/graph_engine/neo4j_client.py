"""
Optional Neo4j mirror of the in-process graph, used for durability and
cross-case graph queries ("has this cluster shown up before?"). Only
touched when GRAPH_BACKEND=neo4j (see app/core/config.py) -- the app
runs fine without a Neo4j instance at all, using NetworkX alone.

Schema mirrors the architecture doc's node/edge taxonomy:
  (:Wallet {address, chain})
  (:KnownEntity {name, type})
  (wallet)-[:SENT {tx_hash, asset, value, timestamp}]->(wallet)
  (wallet)-[:ASSOCIATED_WITH]->(knownEntity)
"""
from neo4j import GraphDatabase

from app.core.config import get_settings


class Neo4jClient:
    def __init__(self):
        settings = get_settings()
        self._driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))

    def close(self) -> None:
        self._driver.close()

    def verify_connectivity(self) -> bool:
        try:
            self._driver.verify_connectivity()
            return True
        except Exception:
            return False

    def upsert_graph(self, nx_graph) -> None:
        with self._driver.session() as session:
            for node, data in nx_graph.nodes(data=True):
                session.run(
                    """
                    MERGE (w:Wallet {address: $address})
                    SET w.chain = $chain, w.kind = $kind
                    """,
                    address=node,
                    chain=data.get("chain"),
                    kind=data.get("kind", "wallet"),
                )
            for u, v, data in nx_graph.edges(data=True):
                session.run(
                    """
                    MATCH (a:Wallet {address: $u}), (b:Wallet {address: $v})
                    MERGE (a)-[r:SENT {tx_hash: $tx_hash}]->(b)
                    SET r.asset = $asset, r.value = $value, r.timestamp = $timestamp
                    """,
                    u=u,
                    v=v,
                    tx_hash=data.get("tx_hash"),
                    asset=data.get("asset"),
                    value=data.get("value"),
                    timestamp=data.get("timestamp"),
                )
