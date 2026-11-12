"""Infraestrutura comum às estratégias de roteamento.

- ``cached_astar``: A* com cache por ``(origem, destino, peso)`` guardado no próprio grafo,
  reutilizado entre chamadas e entre estratégias.
- ``build_cost_matrix``: matriz de custos A* entre um conjunto de nós.
- ``build_route``: transforma uma sequência ordenada de pedidos num ``Route`` completo
  (depósito -> paradas -> depósito), com caminho, ETAs, km, minutos e custo.
- Validações de entrada compartilhadas (pedidos e entregadores ativos).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from rota_core.algorithms.astar import astar_path
from rota_core.domain.models import AStarResult, Courier, Order, Route, RouteStop, Strategy

CACHE_KEY = "astar_cache"
CacheKey = tuple[str, str, str]


class RoutingError(ValueError):
    """Entrada inválida para uma estratégia de roteamento."""


class NoOrdersError(RoutingError):
    """Nenhum pedido para roteirizar."""


class NoActiveCouriersError(RoutingError):
    """Nenhum entregador ativo disponível."""


@dataclass
class AStarCache:
    """Resultados de A* já calculados para um grafo, com contadores de uso."""

    results: dict[CacheKey, AStarResult] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def __len__(self) -> int:
        return len(self.results)


def get_cache(graph: nx.DiGraph) -> AStarCache:
    """Cache do grafo (criado na primeira chamada). Vive enquanto o objeto grafo existir."""
    cache = graph.graph.get(CACHE_KEY)
    if not isinstance(cache, AStarCache):
        cache = AStarCache()
        graph.graph[CACHE_KEY] = cache
    return cache


def clear_cache(graph: nx.DiGraph) -> None:
    """Descarta o cache, por exemplo após alterar arestas do grafo."""
    graph.graph[CACHE_KEY] = AStarCache()


def cached_astar(graph: nx.DiGraph, source: str, target: str, weight: str) -> AStarResult:
    """A* com memoização por ``(source, target, weight)``."""
    cache = get_cache(graph)
    key = (source, target, weight)
    result = cache.results.get(key)
    if result is not None:
        cache.hits += 1
        return result
    cache.misses += 1
    result = astar_path(graph, source, target, weight=weight)
    cache.results[key] = result
    return result


def build_cost_matrix(
    graph: nx.DiGraph,
    node_ids: list[str],
    weight: str = "distance_km",
) -> dict[tuple[str, str], AStarResult]:
    """Custos A* entre todos os pares ordenados distintos de ``node_ids``.

    O grafo é dirigido (pode haver mão única), então ``(a, b)`` e ``(b, a)`` são calculados
    separadamente. Pares desnecessários não são calculados: ids repetidos são ignorados e a
    diagonal ``(a, a)`` (custo zero) fica fora da matriz. Cada resultado vem do cache do grafo,
    cuja chave é ``(origem, destino, peso)``.
    """
    unique = list(dict.fromkeys(node_ids))
    return {
        (source, target): cached_astar(graph, source, target, weight)
        for source in unique
        for target in unique
        if source != target
    }


def leg_cost(graph: nx.DiGraph, source: str, target: str, weight: str) -> float:
    """Custo A* de um trecho no peso escolhido (zero se origem == destino)."""
    if source == target:
        return 0.0
    return cached_astar(graph, source, target, weight).total_cost


def active_couriers(couriers: list[Courier]) -> list[Courier]:
    """Entregadores ativos, ordenados por id. Erro se não houver nenhum."""
    active = sorted((c for c in couriers if c.active), key=lambda c: c.id)
    if not active:
        raise NoActiveCouriersError("não há entregadores ativos para receber os pedidos")
    return active


def require_orders(orders: list[Order]) -> None:
    if not orders:
        raise NoOrdersError("não há pedidos para roteirizar")


def arrival_order(orders: list[Order]) -> list[Order]:
    """Pedidos pela ordem de chegada; empate em ``created_at`` desfeito pelo id."""
    return sorted(orders, key=lambda o: (o.created_at, o.id))


def build_route(
    graph: nx.DiGraph,
    courier: Courier,
    strategy: Strategy,
    ordered_orders: list[Order],
    depot: str,
    weight: str = "distance_km",
    cluster_label: int | None = None,
) -> Route:
    """Monta a rota depósito -> pedidos (na ordem dada) -> depósito.

    - ``path``: todos os nós percorridos, começando e terminando no depósito.
    - ``eta_min`` / ``cumulative_km`` de cada parada: acumulados desde a saída do depósito.
    - ``total_cost`` em R$: ``total_km x courier.cost_per_km``.
    """
    path = [depot]
    stops: list[RouteStop] = []
    km = minutes = 0.0
    current = depot

    def travel(to_node: str) -> None:
        nonlocal km, minutes, current
        if to_node != current:
            leg = cached_astar(graph, current, to_node, weight)
            path.extend(leg.path[1:])
            km += leg.total_distance_km
            minutes += leg.total_time_min
        current = to_node

    for seq, order in enumerate(ordered_orders, start=1):
        if order.node_id is None:
            raise RoutingError(f"pedido {order.id} sem node_id; aplique snap_orders_to_nodes")
        travel(order.node_id)
        stops.append(
            RouteStop(
                order_id=order.id,
                node_id=order.node_id,
                seq=seq,
                eta_min=minutes,
                cumulative_km=km,
            )
        )
    travel(depot)
    if len(path) == 1:  # rota sem deslocamento: ainda assim sai e volta ao depósito
        path.append(depot)

    return Route(
        courier_id=courier.id,
        strategy=strategy,
        cluster_label=cluster_label,
        stops=stops,
        path=path,
        total_km=km,
        total_min=minutes,
        total_cost=km * courier.cost_per_km,
    )
