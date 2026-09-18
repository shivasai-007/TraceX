"""
Graph Engine.

Builds the fund-flow graph for one investigation run in-process with
NetworkX (fast, zero-install, resets when the process restarts) and,
when GRAPH_BACKEND=neo4j is configured, mirrors the same edges into
Neo4j through neo4j_client.py for durable, cross-case graph queries
("has this address ever appeared in another case?").

Node kinds: wallet | known_entity | mixer | bridge | dex | contract
Edge kinds: SENT | RECEIVED | INTERACTED_WITH | BRIDGED_TO
(These names match the architecture diagram / original edge taxonomy.)
"""
from __future__ import annotations

import networkx as nx

from app.core.config import get_settings


class GraphEngine:
    def __init__(self):
        self.settings = get_settings()
        self.g = nx.MultiDiGraph()

    # ---- building -----------------------------------------------------

    def add_wallet(self, address: str, chain: str, **attrs) -> None:
        address = address.lower()
        if not self.g.has_node(address):
            self.g.add_node(address, kind="wallet", chain=chain, **attrs)
        else:
            self.g.nodes[address].update(attrs)

    def tag_node(self, address: str, **attrs) -> None:
        address = address.lower()
        if self.g.has_node(address):
            self.g.nodes[address].update(attrs)
        else:
            self.g.add_node(address, kind="wallet", **attrs)

    def add_transactions(self, normalized_rows: list[dict], chain: str) -> None:
        for row in normalized_rows:
            src = row["from_address"].lower()
            dst = (row["to_address"] or "").lower()
            if not dst:
                continue
            self.add_wallet(src, chain)
            self.add_wallet(dst, chain)
            self.g.add_edge(
                src,
                dst,
                key=row["tx_hash"],
                relation="SENT",
                tx_hash=row["tx_hash"],
                asset=row["asset"],
                value=row["value"],
                timestamp=str(row["timestamp"]),
                method=row.get("method"),
            )

    # ---- reading --------------------------------------------------------

    def hop_subgraph(self, address: str, hops: int) -> nx.MultiDiGraph:
        address = address.lower()
        if address not in self.g:
            return nx.MultiDiGraph()
        undirected = self.g.to_undirected(as_view=True)
        nodes_within = nx.single_source_shortest_path_length(undirected, address, cutoff=hops).keys()
        return self.g.subgraph(nodes_within).copy()

    def wallet_metrics(self, address: str) -> dict:
        address = address.lower()
        if address not in self.g:
            return {
                "in_degree": 0, "out_degree": 0, "counterparties": 0,
                "in_value": 0.0, "out_value": 0.0,
            }
        in_edges = list(self.g.in_edges(address, data=True))
        out_edges = list(self.g.out_edges(address, data=True))
        counterparties = {u for u, _v, _d in in_edges} | {v for _u, v, _d in out_edges}
        counterparties.discard(address)
        return {
            "in_degree": len(in_edges),
            "out_degree": len(out_edges),
            "counterparties": len(counterparties),
            "in_value": sum(d.get("value", 0) for *_e, d in in_edges),
            "out_value": sum(d.get("value", 0) for *_e, d in out_edges),
        }

    def node_count(self) -> int:
        return self.g.number_of_nodes()

    def edge_count(self) -> int:
        return self.g.number_of_edges()

    # ---- export for the React "Interactive Investigation Workspace" -----

    def to_frontend_json(self, focus_address: str, subgraph: nx.MultiDiGraph | None = None) -> dict:
        sg = subgraph if subgraph is not None else self.g
        focus_address = focus_address.lower()
        nodes = [
            {
                "id": n,
                "kind": data.get("kind", "wallet"),
                "chain": data.get("chain"),
                "label": data.get("label", n),
                "isFocus": n == focus_address,
                "entityType": data.get("entity_type"),
                "entityName": data.get("entity_name"),
            }
            for n, data in sg.nodes(data=True)
        ]
        edges = [
            {
                "id": f"{u}-{v}-{data.get('tx_hash', k)}",
                "source": u,
                "target": v,
                "asset": data.get("asset"),
                "value": data.get("value"),
                "timestamp": data.get("timestamp"),
                "txHash": data.get("tx_hash"),
            }
            for u, v, k, data in sg.edges(keys=True, data=True)
        ]
        return {"nodes": nodes, "edges": edges}

    # ---- optional durability ------------------------------------------

    def persist_to_neo4j(self) -> None:
        if self.settings.graph_backend != "neo4j":
            return
        from app.graph_engine.neo4j_client import Neo4jClient  # local import: optional dependency path

        client = Neo4jClient()
        try:
            client.upsert_graph(self.g)
        finally:
            client.close()
