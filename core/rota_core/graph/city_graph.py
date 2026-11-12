"""Representação da cidade como grafo (NetworkX) e utilitários geográficos."""

from __future__ import annotations

import math

import networkx as nx

from rota_core.domain.models import Edge, Node, NodeKind

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em linha reta (km) entre duas coordenadas geográficas."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def build_city_graph(nodes: list[Node], edges: list[Edge]) -> nx.DiGraph:
    """Monta um grafo dirigido. Ruas de mão dupla viram dois arcos.

    Atributos dos nós: ``name``, ``kind``, ``lat``, ``lon``.
    Atributos dos arcos: ``distance_km``, ``speed_kmh``, ``time_min``.
    """
    graph = nx.DiGraph()
    for node in nodes:
        graph.add_node(node.id, name=node.name, kind=node.kind.value, lat=node.lat, lon=node.lon)

    for edge in edges:
        attrs = {
            "distance_km": edge.distance_km,
            "speed_kmh": edge.speed_kmh,
            "time_min": edge.time_min,
        }
        graph.add_edge(edge.source, edge.target, **attrs)
        if not edge.oneway:
            graph.add_edge(edge.target, edge.source, **attrs)
    return graph


def depot_id(graph: nx.DiGraph) -> str:
    """Retorna o id do único nó depósito."""
    depots = [n for n, kind in graph.nodes(data="kind") if kind == NodeKind.DEPOT.value]
    if len(depots) != 1:
        raise ValueError(f"esperado exatamente 1 depósito, encontrado {len(depots)}")
    return depots[0]
