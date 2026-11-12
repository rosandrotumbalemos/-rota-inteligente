"""Estratégia principal: K-Means + A* (com vizinho mais próximo, 2-opt e atribuição húngara).

Pipeline:

1. **Snap**: cada pedido é ligado ao nó mais próximo do grafo.
2. **K-Means**: pedidos agrupados em ``k`` zonas pela posição (km), ``random_state`` fixo.
3. **Balanceamento**: nenhuma zona passa de ``ceil(n/k) + max_extra`` pedidos; nenhuma fica vazia.
4. **Sequência inicial**: em cada zona, vizinho mais próximo a partir do depósito (custo A*).
5. **2-opt**: melhora a ordem de visita; só aceita movimentos que reduzem o custo.
6. **Atribuição**: zona -> entregador pelo algoritmo húngaro, minimizando R$ (km x custo/km).
   A atribuição vem depois do sequenciamento porque precisa do km de cada zona.
7. **Rotas**: trechos pelo A* (cache do grafo), depósito -> pedidos -> depósito.

Com ``k`` = nº de entregadores ativos (padrão), todos recebem uma zona. ``k`` maior que o
número de entregadores é recusado: cada zona precisa de exatamente um entregador.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from rota_core.algorithms.assignment import assign_zones, snap_orders_to_nodes
from rota_core.algorithms.kmeans_zones import balance_zones, cluster_orders
from rota_core.algorithms.nearest_neighbor import greedy_sequence
from rota_core.algorithms.routing import (
    RoutingError,
    active_couriers,
    build_route,
    cached_astar,
    leg_cost,
    require_orders,
)
from rota_core.algorithms.two_opt import tour_cost, two_opt
from rota_core.domain.models import Courier, Order, Route, Strategy, Zone
from rota_core.graph.city_graph import depot_id


@dataclass
class KMeansAStarPlan:
    """Resultado detalhado da estratégia, útil para relatórios e mapas."""

    zones: list[Zone]
    initial_sequences: dict[int, list[Order]]
    sequences: dict[int, list[Order]]
    initial_cost: dict[int, float]
    final_cost: dict[int, float]
    zone_km: dict[int, float]
    assignment: dict[int, str]
    routes: list[Route] = field(default_factory=list)


def _node(item: str | Order) -> str:
    return item if isinstance(item, str) else item.node_id


def sequence_km(graph: nx.DiGraph, sequence: list[Order], depot: str) -> float:
    """Km de depósito -> sequência -> depósito, somando os trechos A* (peso distância)."""
    nodes = [depot, *(o.node_id for o in sequence), depot]
    return sum(
        cached_astar(graph, u, v, "distance_km").total_distance_km
        for u, v in zip(nodes, nodes[1:], strict=False)
        if u != v
    )


def kmeans_astar_plan(
    graph: nx.DiGraph,
    orders: list[Order],
    couriers: list[Courier],
    weight: str = "distance_km",
    k: int | None = None,
    seed: int = 42,
    max_extra: int = 2,
) -> KMeansAStarPlan:
    """Executa o pipeline completo e devolve zonas, sequências, atribuição e rotas."""
    require_orders(orders)
    team = active_couriers(couriers)
    depot = depot_id(graph)
    k = len(team) if k is None else k
    if k > len(team):
        raise RoutingError(f"k={k} zonas para {len(team)} entregadores ativos")

    snapped = snap_orders_to_nodes(graph, orders)
    zones = balance_zones(cluster_orders(snapped, k, seed=seed), max_extra=max_extra)

    def cost(u: str | Order, v: str | Order) -> float:
        return leg_cost(graph, _node(u), _node(v), weight)

    initial, final, initial_cost, final_cost, zone_km = {}, {}, {}, {}, {}
    for zone in zones:
        pool = {o.id: o for o in zone.orders}
        start = greedy_sequence(graph, depot, pool, weight)
        improved = two_opt(start, cost, depot)
        cid = zone.cluster_id
        initial[cid], final[cid] = start, improved
        initial_cost[cid] = tour_cost(start, cost, depot)
        final_cost[cid] = tour_cost(improved, cost, depot)
        zone_km[cid] = sequence_km(graph, improved, depot)

    assignment = assign_zones(zones, team, zone_km)
    by_id = {c.id: c for c in team}
    routes = sorted(
        (
            build_route(
                graph,
                by_id[courier_id],
                Strategy.KMEANS_ASTAR,
                final[cid],
                depot,
                weight,
                cluster_label=cid,
            )
            for cid, courier_id in assignment.items()
        ),
        key=lambda r: r.courier_id,
    )
    return KMeansAStarPlan(
        zones=zones,
        initial_sequences=initial,
        sequences=final,
        initial_cost=initial_cost,
        final_cost=final_cost,
        zone_km=zone_km,
        assignment=assignment,
        routes=routes,
    )


def kmeans_astar_routes(
    graph: nx.DiGraph,
    orders: list[Order],
    couriers: list[Courier],
    weight: str = "distance_km",
    k: int | None = None,
    seed: int = 42,
    max_extra: int = 2,
) -> list[Route]:
    """Rotas da estratégia K-Means + A*, uma por zona (ordenadas por entregador)."""
    return kmeans_astar_plan(graph, orders, couriers, weight, k, seed, max_extra).routes
