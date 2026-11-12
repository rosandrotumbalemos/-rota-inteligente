"""Busca A* (A-estrela) do menor caminho no grafo da cidade.

O A* expande primeiro o nó com menor ``f(n) = g(n) + h(n)``:

- ``g(n)``: custo real acumulado da origem até ``n`` (soma dos pesos dos arcos);
- ``h(n)``: estimativa do custo restante de ``n`` até o destino (heurística).

Heurísticas usadas (ambas admissíveis, isto é, nunca superestimam o custo real):

- peso ``"distance_km"``: ``h(n) = haversine_km(n, destino)``. Nenhuma rua é mais curta que a
  linha reta entre seus extremos, então nenhum caminho é mais curto que a linha reta.
- peso ``"time_min"``: ``h(n) = haversine_km(n, destino) / v_max * 60``, com ``v_max`` = maior
  velocidade (km/h) presente nas arestas do grafo. Nenhum trecho pode ser percorrido mais rápido
  que a linha reta na velocidade máxima.

Com heurística admissível o A* devolve o caminho ótimo. Arcos dirigidos são respeitados, então
ruas de mão única funcionam: o grafo vem de ``rota_core.graph.city_graph.build_city_graph``.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable
from itertools import count

import networkx as nx

from rota_core.domain.models import AStarResult
from rota_core.graph.city_graph import haversine_km

SUPPORTED_WEIGHTS: tuple[str, ...] = ("distance_km", "time_min")

Heuristic = Callable[[str], float]


class AStarError(ValueError):
    """Erro base do A*."""


class NodeNotFoundError(AStarError):
    """Nó de origem ou destino inexistente no grafo."""


class NoPathError(AStarError):
    """Não existe caminho dirigido entre origem e destino."""


def max_speed_kmh(graph: nx.DiGraph) -> float:
    """Maior velocidade (km/h) entre os arcos do grafo; usada na heurística de tempo."""
    speeds = [speed for _, _, speed in graph.edges(data="speed_kmh") if speed is not None]
    if not speeds:
        raise AStarError("o grafo não tem arcos com o atributo 'speed_kmh'")
    vmax = max(speeds)
    if vmax <= 0:
        raise AStarError("velocidade máxima do grafo deve ser positiva")
    return float(vmax)


def make_heuristic(graph: nx.DiGraph, target: str, weight: str = "distance_km") -> Heuristic:
    """Cria ``h(n)`` para o destino e o peso informados."""
    _check_weight(weight)
    t_lat, t_lon = graph.nodes[target]["lat"], graph.nodes[target]["lon"]

    def straight_km(node: str) -> float:
        data = graph.nodes[node]
        return haversine_km(data["lat"], data["lon"], t_lat, t_lon)

    if weight == "distance_km":
        return straight_km

    vmax = max_speed_kmh(graph)
    return lambda node: straight_km(node) / vmax * 60


def path_totals(graph: nx.DiGraph, path: list[str]) -> tuple[float, float]:
    """Soma ``(distância em km, tempo em min)`` dos arcos de um caminho."""
    distance = time = 0.0
    for u, v in zip(path, path[1:], strict=False):
        if not graph.has_edge(u, v):
            raise NoPathError(f"não há arco {u} -> {v}")
        data = graph.edges[u, v]
        distance += data["distance_km"]
        time += data["time_min"]
    return distance, time


def astar_path(
    graph: nx.DiGraph,
    source: str,
    target: str,
    weight: str = "distance_km",
) -> AStarResult:
    """Menor caminho de ``source`` a ``target`` minimizando ``weight``.

    Args:
        graph: grafo dirigido com ``lat``/``lon`` nos nós e ``distance_km``, ``time_min``
            e ``speed_kmh`` nos arcos.
        source: id do nó de origem.
        target: id do nó de destino.
        weight: ``"distance_km"`` ou ``"time_min"``.

    Returns:
        ``AStarResult`` com caminho, custo no peso escolhido, distância e tempo totais.

    Raises:
        ValueError: peso não suportado ou arco com peso negativo.
        NodeNotFoundError: origem ou destino não existe.
        NoPathError: não há caminho dirigido entre os nós.
    """
    _check_weight(weight)
    for label, node in (("origem", source), ("destino", target)):
        if node not in graph:
            raise NodeNotFoundError(f"nó de {label} não existe no grafo: {node!r}")

    if source == target:
        return AStarResult(path=[source], weight=weight)

    h = make_heuristic(graph, target, weight)
    tie = count()  # desempate estável quando dois nós têm o mesmo f
    g_score: dict[str, float] = {source: 0.0}
    came_from: dict[str, str] = {}
    open_heap: list[tuple[float, int, float, str]] = [(h(source), next(tie), 0.0, source)]
    expanded = 0

    while open_heap:
        _, _, g_current, current = heapq.heappop(open_heap)
        if g_current > g_score.get(current, math.inf):
            continue  # entrada desatualizada: já achamos caminho melhor para este nó
        expanded += 1

        if current == target:
            path = _rebuild_path(came_from, target)
            distance, time = path_totals(graph, path)
            return AStarResult(
                path=path,
                total_cost=g_current,
                total_distance_km=distance,
                total_time_min=time,
                weight=weight,
                expanded_nodes=expanded,
            )

        for neighbor, data in graph.succ[current].items():
            cost = data[weight]
            if cost < 0:
                raise ValueError(f"arco {current} -> {neighbor} com peso negativo: {cost}")
            tentative = g_current + cost
            if tentative < g_score.get(neighbor, math.inf):
                g_score[neighbor] = tentative
                came_from[neighbor] = current
                heapq.heappush(open_heap, (tentative + h(neighbor), next(tie), tentative, neighbor))

    raise NoPathError(f"não existe caminho de {source!r} para {target!r}")


def _rebuild_path(came_from: dict[str, str], target: str) -> list[str]:
    path = [target]
    while path[-1] in came_from:
        path.append(came_from[path[-1]])
    path.reverse()
    return path


def _check_weight(weight: str) -> None:
    if weight not in SUPPORTED_WEIGHTS:
        raise ValueError(f"peso não suportado: {weight!r}; use um de {SUPPORTED_WEIGHTS}")
