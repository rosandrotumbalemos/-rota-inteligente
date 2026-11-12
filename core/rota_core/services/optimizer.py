"""Orquestra as estratégias de roteamento sobre um dataset e mede o tempo de cada uma.

Comparação justa: cada estratégia roda num grafo novo, com o cache do A* vazio. Assim o tempo
de cálculo de uma não se beneficia dos trechos já calculados por outra, e o resultado não
depende da ordem de execução.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import networkx as nx

from rota_core.algorithms.kmeans_astar import KMeansAStarPlan, kmeans_astar_plan
from rota_core.algorithms.manual import manual_routes
from rota_core.algorithms.nearest_neighbor import nearest_neighbor_routes
from rota_core.data.loaders import Dataset
from rota_core.domain.models import Route, Strategy
from rota_core.graph.city_graph import build_city_graph

ALL_STRATEGIES: tuple[str, ...] = tuple(s.value for s in Strategy)


@dataclass
class OptimizationResult:
    """Rotas e tempo de cálculo (ms) de cada estratégia executada."""

    graph: nx.DiGraph
    routes: dict[str, list[Route]] = field(default_factory=dict)
    compute_ms: dict[str, float] = field(default_factory=dict)
    kmeans_plan: KMeansAStarPlan | None = None
    weight: str = "distance_km"


def optimize(
    dataset: Dataset,
    strategies: list[str] | tuple[str, ...] = ALL_STRATEGIES,
    weight: str = "distance_km",
    k: int | None = None,
    seed: int = 42,
    max_extra: int = 2,
) -> OptimizationResult:
    """Executa as estratégias pedidas, na ordem dada, cada uma num grafo com cache vazio.

    Raises:
        ValueError: estratégia desconhecida (e os erros de cada estratégia, ex. sem pedidos).
    """
    unknown = [s for s in strategies if s not in ALL_STRATEGIES]
    if unknown:
        raise ValueError(f"estratégia desconhecida: {unknown}")

    result = OptimizationResult(graph=build_city_graph(dataset.nodes, dataset.edges), weight=weight)
    for name in strategies:
        graph = build_city_graph(dataset.nodes, dataset.edges)  # cache vazio
        start = time.perf_counter()
        if name == Strategy.MANUAL.value:
            routes = manual_routes(graph, dataset.orders, dataset.couriers, weight=weight)
        elif name == Strategy.NEAREST_NEIGHBOR.value:
            routes = nearest_neighbor_routes(graph, dataset.orders, dataset.couriers, weight=weight)
        else:
            plan = kmeans_astar_plan(
                graph,
                dataset.orders,
                dataset.couriers,
                weight=weight,
                k=k,
                seed=seed,
                max_extra=max_extra,
            )
            result.kmeans_plan = plan
            routes = plan.routes
        result.compute_ms[name] = (time.perf_counter() - start) * 1000
        result.routes[name] = routes
    return result
