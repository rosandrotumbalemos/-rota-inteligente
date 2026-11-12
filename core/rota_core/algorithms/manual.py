"""Estratégia manual (baseline): simula como a Sabor Express trabalha hoje.

1. Pedidos em ordem de chegada (``created_at``; empate pelo id).
2. Distribuição em rodízio: 1º pedido -> 1º entregador, 2º -> 2º, ..., e recomeça.
3. Cada entregador visita seus pedidos na ordem de chegada, sem otimizar a sequência.
4. Os trechos depósito -> pedidos -> depósito usam o caminho ótimo do A* (o entregador
   conhece as ruas; o que não é otimizado é a divisão e a ordem das entregas).

Entregadores sem pedidos não geram rota.
"""

from __future__ import annotations

import networkx as nx

from rota_core.algorithms.assignment import snap_orders_to_nodes
from rota_core.algorithms.routing import (
    active_couriers,
    arrival_order,
    build_route,
    require_orders,
)
from rota_core.domain.models import Courier, Order, Route, Strategy
from rota_core.graph.city_graph import depot_id


def manual_routes(
    graph: nx.DiGraph,
    orders: list[Order],
    couriers: list[Courier],
    weight: str = "distance_km",
) -> list[Route]:
    """Rotas da estratégia manual, uma por entregador que recebeu pedidos."""
    require_orders(orders)
    team = active_couriers(couriers)
    depot = depot_id(graph)
    snapped = snap_orders_to_nodes(graph, orders)

    buckets: dict[str, list[Order]] = {c.id: [] for c in team}
    for index, order in enumerate(arrival_order(snapped)):
        buckets[team[index % len(team)].id].append(order)

    return [
        build_route(graph, courier, Strategy.MANUAL, buckets[courier.id], depot, weight)
        for courier in team
        if buckets[courier.id]
    ]
