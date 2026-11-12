"""Montagem do grafo da cidade e distância Haversine."""

from __future__ import annotations

import networkx as nx
import pytest

from rota_core.graph import build_city_graph, depot_id, haversine_km


def test_haversine_conhecido() -> None:
    # Praça da Sé -> Av. Paulista/MASP: aprox. 2,6 km em linha reta
    d = haversine_km(-23.5505, -46.6333, -23.5614, -46.6559)
    assert d == pytest.approx(2.65, abs=0.3)
    assert haversine_km(-23.55, -46.63, -23.55, -46.63) == 0


def test_grafo_fortemente_conexo(dataset) -> None:
    graph = build_city_graph(dataset.nodes, dataset.edges)
    assert graph.number_of_nodes() == 40
    assert graph.number_of_edges() == 120  # 60 ruas de mão dupla
    assert nx.is_strongly_connected(graph)


def test_atributos_das_arestas(dataset) -> None:
    graph = build_city_graph(dataset.nodes, dataset.edges)
    for _, _, data in graph.edges(data=True):
        assert data["distance_km"] > 0
        assert data["time_min"] == pytest.approx(data["distance_km"] / data["speed_kmh"] * 60)


def test_distancia_de_rua_maior_que_linha_reta(dataset) -> None:
    graph = build_city_graph(dataset.nodes, dataset.edges)
    for u, v, data in graph.edges(data=True):
        a, b = graph.nodes[u], graph.nodes[v]
        assert data["distance_km"] >= haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])


def test_depot_id(dataset) -> None:
    assert depot_id(build_city_graph(dataset.nodes, dataset.edges)) == "N00"
