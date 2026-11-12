"""Associação de pedidos ao grafo e (na Etapa 5) de zonas a entregadores.

- ``snap_orders_to_nodes``: liga cada pedido ao nó mais próximo (Haversine). Implementado.
- ``assign_zones``: zona -> entregador pelo algoritmo húngaro (``scipy.optimize``).
"""

from __future__ import annotations

import networkx as nx
import numpy as np
from scipy.optimize import linear_sum_assignment

from rota_core.domain.models import Courier, Order, Zone
from rota_core.graph.city_graph import haversine_km


class EmptyGraphError(ValueError):
    """O grafo não tem nós para receber os pedidos."""


def nearest_node(graph: nx.DiGraph, lat: float, lon: float) -> str:
    """Id do nó mais próximo da coordenada. Empate desfeito pelo menor id (determinístico)."""
    if graph.number_of_nodes() == 0:
        raise EmptyGraphError("o grafo não tem nós")
    return min(
        sorted(graph.nodes),
        key=lambda n: haversine_km(lat, lon, graph.nodes[n]["lat"], graph.nodes[n]["lon"]),
    )


def snap_orders_to_nodes(graph: nx.DiGraph, orders: list[Order]) -> list[Order]:
    """Retorna cópias dos pedidos com ``node_id`` = nó mais próximo (Haversine).

    Os pedidos originais não são alterados (os modelos são imutáveis; usamos ``model_copy``).
    Pedidos que já têm ``node_id`` são recalculados, para refletir o grafo informado.
    """
    if graph.number_of_nodes() == 0:
        raise EmptyGraphError("o grafo não tem nós para associar os pedidos")
    return [
        order.model_copy(update={"node_id": nearest_node(graph, order.lat, order.lon)})
        for order in orders
    ]


class AssignmentError(ValueError):
    """Não é possível atribuir as zonas aos entregadores."""


def zone_cost_matrix(
    zones: list[Zone], couriers: list[Courier], zone_km: dict[int, float]
) -> np.ndarray:
    """Matriz zonas x entregadores: custo em R$ = km estimado da zona x custo/km do entregador."""
    return np.array([[zone_km[z.cluster_id] * c.cost_per_km for c in couriers] for z in zones])


def assign_zones(
    zones: list[Zone],
    couriers: list[Courier],
    zone_km: dict[int, float],
) -> dict[int, str]:
    """Atribui cada zona a um entregador distinto minimizando o custo total em R$.

    Usa ``scipy.optimize.linear_sum_assignment`` (algoritmo húngaro / Jonker-Volgenant), que
    encontra a atribuição ótima de custo mínimo em tempo polinomial.

    Args:
        zones: zonas já formadas.
        couriers: entregadores ativos, na ordem desejada para desempates.
        zone_km: km estimado da rota de cada zona (depósito -> pedidos -> depósito).

    Returns:
        ``{cluster_id: courier_id}``. Com mais entregadores que zonas, alguns ficam sem zona.

    Raises:
        AssignmentError: mais zonas que entregadores, ou listas vazias.
    """
    if not zones:
        raise AssignmentError("não há zonas para atribuir")
    if not couriers:
        raise AssignmentError("não há entregadores para receber as zonas")
    if len(zones) > len(couriers):
        raise AssignmentError(
            f"{len(zones)} zonas para {len(couriers)} entregadores: cada zona precisa de um"
        )
    rows, cols = linear_sum_assignment(zone_cost_matrix(zones, couriers, zone_km))
    return {zones[r].cluster_id: couriers[c].id for r, c in zip(rows, cols, strict=True)}
