"""Estratégia do vizinho mais próximo (heurística gulosa, sem clustering).

Carga equilibrada: com ``n`` pedidos e ``k`` entregadores, cada um recebe ``n // k`` pedidos e
os ``n % k`` primeiros (por id) recebem um a mais.

Os entregadores são roteirizados um de cada vez, em ordem de id:

1. Começa no depósito.
2. A cada passo, vai ao pedido ainda não atendido (por nenhum entregador) com menor custo A*
   a partir do ponto atual, no peso escolhido. Empate: menor id do pedido.
3. Ao completar sua cota, volta ao depósito.

Limitação conhecida (e motivo do K-Means na Etapa 5): os primeiros entregadores pegam os
pedidos mais próximos e os últimos ficam com o que sobra, muitas vezes espalhado pela cidade.
Entregadores sem pedidos (mais entregadores que pedidos) não geram rota.
"""

from __future__ import annotations

import networkx as nx

from rota_core.algorithms.assignment import snap_orders_to_nodes
from rota_core.algorithms.routing import (
    active_couriers,
    build_route,
    leg_cost,
    require_orders,
)
from rota_core.domain.models import Courier, Order, Route, Strategy
from rota_core.graph.city_graph import depot_id


def balanced_quotas(n_orders: int, n_couriers: int) -> list[int]:
    """Quantos pedidos cada entregador recebe; as cotas diferem em no máximo 1."""
    base, extra = divmod(n_orders, n_couriers)
    return [base + (1 if i < extra else 0) for i in range(n_couriers)]


def greedy_sequence(
    graph: nx.DiGraph,
    start: str,
    pool: dict[str, Order],
    weight: str = "distance_km",
    limit: int | None = None,
) -> list[Order]:
    """Sequência gulosa: a partir de ``start``, vai sempre ao pedido do ``pool`` com menor
    custo A* (empate: menor id). Remove do ``pool`` os pedidos escolhidos.

    ``limit`` = quantos pedidos tirar do pool (``None`` = todos).
    """
    current, sequence = start, []
    steps = len(pool) if limit is None else min(limit, len(pool))
    for _ in range(steps):
        chosen = min(
            pool.values(),
            key=lambda o, cur=current: (leg_cost(graph, cur, o.node_id, weight), o.id),
        )
        sequence.append(chosen)
        del pool[chosen.id]
        current = chosen.node_id
    return sequence


def nearest_neighbor_routes(
    graph: nx.DiGraph,
    orders: list[Order],
    couriers: list[Courier],
    weight: str = "distance_km",
) -> list[Route]:
    """Rotas gulosas do vizinho mais próximo, uma por entregador que recebeu pedidos."""
    require_orders(orders)
    team = active_couriers(couriers)
    depot = depot_id(graph)
    pending = {o.id: o for o in snap_orders_to_nodes(graph, orders)}

    routes: list[Route] = []
    for courier, quota in zip(team, balanced_quotas(len(pending), len(team)), strict=True):
        if quota == 0:
            continue
        sequence = greedy_sequence(graph, depot, pending, weight, limit=quota)
        routes.append(
            build_route(graph, courier, Strategy.NEAREST_NEIGHBOR, sequence, depot, weight)
        )
    return routes
