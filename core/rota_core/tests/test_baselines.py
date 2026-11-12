"""Testes da Etapa 4: snap, matriz de custos com cache, rota manual e vizinho mais próximo."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

import networkx as nx
import pytest

from rota_core.algorithms.assignment import EmptyGraphError, nearest_node, snap_orders_to_nodes
from rota_core.algorithms.manual import manual_routes
from rota_core.algorithms.nearest_neighbor import balanced_quotas, nearest_neighbor_routes
from rota_core.algorithms.routing import (
    NoActiveCouriersError,
    NoOrdersError,
    arrival_order,
    build_cost_matrix,
    clear_cache,
    get_cache,
    leg_cost,
)
from rota_core.config import REPO_ROOT
from rota_core.data import load_dataset
from rota_core.domain import Courier, Order, Route, Strategy
from rota_core.graph import build_city_graph, depot_id
from rota_core.graph.city_graph import haversine_km

STRATEGIES = {
    "manual": manual_routes,
    "nearest_neighbor": nearest_neighbor_routes,
}
WEIGHTS = ("distance_km", "time_min")


@pytest.fixture(scope="module")
def data():
    return load_dataset(REPO_ROOT / "data")


@pytest.fixture()
def graph(data) -> nx.DiGraph:
    """Grafo novo por teste: cada teste começa com o cache vazio."""
    return build_city_graph(data.nodes, data.edges)


def _order(order_id: str, lat: float, lon: float, minute: int = 0) -> Order:
    return Order(
        id=order_id,
        code=f"SE-{order_id}",
        customer_alias="Cliente teste",
        address_label="Endereço fictício",
        lat=lat,
        lon=lon,
        created_at=datetime(2026, 11, 12, 12, minute),
        value=50,
    )


def _all_routes(graph, data, weight="distance_km") -> dict[str, list[Route]]:
    return {
        name: fn(graph, data.orders, data.couriers, weight=weight)
        for name, fn in STRATEGIES.items()
    }


# 1. Snap ao nó mais próximo -----------------------------------------------------------------
def test_snap_no_mais_proximo(graph, data) -> None:
    snapped = snap_orders_to_nodes(graph, data.orders)
    for order in snapped:
        chosen = haversine_km(
            order.lat,
            order.lon,
            graph.nodes[order.node_id]["lat"],
            graph.nodes[order.node_id]["lon"],
        )
        for _, attrs in graph.nodes(data=True):
            assert chosen <= haversine_km(order.lat, order.lon, attrs["lat"], attrs["lon"]) + 1e-12


def test_snap_pedido_sobre_o_no(graph) -> None:
    lat, lon = graph.nodes["N07"]["lat"], graph.nodes["N07"]["lon"]
    assert snap_orders_to_nodes(graph, [_order("T1", lat, lon)])[0].node_id == "N07"


def test_snap_nao_altera_original(graph, data) -> None:
    snapped = snap_orders_to_nodes(graph, data.orders)
    assert all(o.node_id is None for o in data.orders)
    assert all(o.node_id is not None for o in snapped)
    assert [o.id for o in snapped] == [o.id for o in data.orders]


def test_snap_grafo_vazio() -> None:
    with pytest.raises(EmptyGraphError):
        snap_orders_to_nodes(nx.DiGraph(), [_order("T1", -23.55, -46.63)])


# 2. Snap determinístico ---------------------------------------------------------------------
def test_snap_deterministico(graph, data) -> None:
    first = [o.node_id for o in snap_orders_to_nodes(graph, data.orders)]
    second = [o.node_id for o in snap_orders_to_nodes(graph, data.orders)]
    assert first == second


def test_snap_empate_pelo_menor_id() -> None:
    g = nx.DiGraph()
    g.add_node("B", lat=-23.55, lon=-46.62)
    g.add_node("A", lat=-23.55, lon=-46.64)
    assert nearest_node(g, -23.55, -46.63) == "A"  # equidistante de A e B


# 3 e 4. Rota manual -------------------------------------------------------------------------
def test_manual_rodizio(graph, data) -> None:
    routes = manual_routes(graph, data.orders, data.couriers)
    owner = {s.order_id: r.courier_id for r in routes for s in r.stops}
    couriers = sorted(c.id for c in data.couriers if c.active)
    for index, order in enumerate(arrival_order(data.orders)):
        assert owner[order.id] == couriers[index % len(couriers)]


def test_manual_ordem_de_chegada(graph, data) -> None:
    by_id = {o.id: o for o in data.orders}
    for route in manual_routes(graph, data.orders, data.couriers):
        keys = [(by_id[s.order_id].created_at, s.order_id) for s in route.stops]
        assert keys == sorted(keys)


# 5. Vizinho mais próximo --------------------------------------------------------------------
@pytest.mark.parametrize("weight", WEIGHTS)
def test_vizinho_escolhe_sempre_o_mais_proximo(graph, data, weight) -> None:
    routes = nearest_neighbor_routes(graph, data.orders, data.couriers, weight=weight)
    snapped = {o.id: o for o in snap_orders_to_nodes(graph, data.orders)}
    available = set(snapped)
    depot = depot_id(graph)
    for route in routes:  # entregadores são roteirizados em sequência, por id
        current = depot
        for stop in route.stops:
            chosen_cost = leg_cost(graph, current, stop.node_id, weight)
            for other in available:
                assert (
                    chosen_cost <= leg_cost(graph, current, snapped[other].node_id, weight) + 1e-9
                )
            available.remove(stop.order_id)
            current = stop.node_id
    assert not available


def test_vizinho_carga_equilibrada(graph, data) -> None:
    sizes = [len(r.stops) for r in nearest_neighbor_routes(graph, data.orders, data.couriers)]
    assert max(sizes) - min(sizes) <= 1
    assert balanced_quotas(10, 4) == [3, 3, 2, 2]


# 6 a 10. Propriedades comuns às duas estratégias --------------------------------------------
@pytest.mark.parametrize("name", STRATEGIES)
@pytest.mark.parametrize("weight", WEIGHTS)
def test_rotas_comecam_e_terminam_no_deposito(graph, data, name, weight) -> None:
    depot = depot_id(graph)
    for route in STRATEGIES[name](graph, data.orders, data.couriers, weight=weight):
        assert route.path[0] == depot
        assert route.path[-1] == depot
        assert all(graph.has_edge(u, v) for u, v in zip(route.path, route.path[1:], strict=False))
        assert route.strategy == Strategy(name)


@pytest.mark.parametrize("name", STRATEGIES)
def test_cada_pedido_exatamente_uma_vez(graph, data, name) -> None:
    routes = STRATEGIES[name](graph, data.orders, data.couriers)
    counts = Counter(s.order_id for r in routes for s in r.stops)
    assert set(counts) == {o.id for o in data.orders}  # nenhum pedido sem rota
    assert all(c == 1 for c in counts.values())


@pytest.mark.parametrize("name", STRATEGIES)
def test_nenhum_pedido_sem_rota_e_paradas_no_caminho(graph, data, name) -> None:
    for route in STRATEGIES[name](graph, data.orders, data.couriers):
        assert route.stops, "rotas vazias não são geradas"
        assert [s.seq for s in route.stops] == list(range(1, len(route.stops) + 1))
        assert all(s.node_id in route.path for s in route.stops)


@pytest.mark.parametrize("name", STRATEGIES)
def test_km_e_tempo_nao_negativos_e_acumulados(graph, data, name) -> None:
    for route in STRATEGIES[name](graph, data.orders, data.couriers):
        assert route.total_km >= 0
        assert route.total_min >= 0
        etas = [s.eta_min for s in route.stops]
        assert etas == sorted(etas)
        assert route.stops[-1].cumulative_km <= route.total_km + 1e-9


@pytest.mark.parametrize("name", STRATEGIES)
def test_totais_batem_com_o_caminho(graph, data, name) -> None:
    for route in STRATEGIES[name](graph, data.orders, data.couriers):
        edges = list(zip(route.path, route.path[1:], strict=False))
        assert route.total_km == pytest.approx(sum(graph.edges[e]["distance_km"] for e in edges))
        assert route.total_min == pytest.approx(sum(graph.edges[e]["time_min"] for e in edges))


# 11. Custo com custo_por_km -----------------------------------------------------------------
@pytest.mark.parametrize("name", STRATEGIES)
def test_custo_usa_custo_por_km(graph, data, name) -> None:
    cost_per_km = {c.id: c.cost_per_km for c in data.couriers}
    for route in STRATEGIES[name](graph, data.orders, data.couriers):
        assert route.total_cost == pytest.approx(route.total_km * cost_per_km[route.courier_id])


# 12. Cache da matriz de custos --------------------------------------------------------------
def test_matriz_usa_cache(graph) -> None:
    clear_cache(graph)
    nodes = ["N00", "N05", "N10", "N05", "N20"]  # N05 repetido: não gera pares extras
    first = build_cost_matrix(graph, nodes)
    cache = get_cache(graph)
    assert len(first) == 4 * 3  # pares ordenados distintos, sem diagonal
    assert cache.misses == 12
    assert cache.hits == 0

    second = build_cost_matrix(graph, nodes)
    assert cache.misses == 12  # nada recalculado
    assert cache.hits == 12
    assert all(second[k] is first[k] for k in first)
    assert set(cache.results) == {(s, t, "distance_km") for s, t in first}


def test_cache_reutilizado_entre_estrategias(graph, data) -> None:
    manual_routes(graph, data.orders, data.couriers)
    misses_after_first = get_cache(graph).misses
    manual_routes(graph, data.orders, data.couriers)
    assert get_cache(graph).misses == misses_after_first
    assert get_cache(graph).hits > 0


# 13. Matriz para distância e tempo ----------------------------------------------------------
@pytest.mark.parametrize("weight", WEIGHTS)
def test_matriz_por_peso(graph, weight) -> None:
    nodes = ["N00", "N03", "N11", "N27", "N39"]
    matrix = build_cost_matrix(graph, nodes, weight=weight)
    for (s, t), result in matrix.items():
        assert result.weight == weight
        assert result.total_cost == pytest.approx(nx.dijkstra_path_length(graph, s, t, weight))
    assert all(key[2] == weight for key in get_cache(graph).results)


def test_matriz_separa_pesos_no_cache(graph) -> None:
    clear_cache(graph)
    build_cost_matrix(graph, ["N00", "N01"], weight="distance_km")
    build_cost_matrix(graph, ["N00", "N01"], weight="time_min")
    assert len(get_cache(graph)) == 4


# 14 e 15. Erros ------------------------------------------------------------------------------
@pytest.mark.parametrize("name", STRATEGIES)
def test_erro_sem_entregadores_ativos(graph, data, name) -> None:
    inactive = [c.model_copy(update={"active": False}) for c in data.couriers]
    with pytest.raises(NoActiveCouriersError, match="entregadores ativos"):
        STRATEGIES[name](graph, data.orders, inactive)
    with pytest.raises(NoActiveCouriersError):
        STRATEGIES[name](graph, data.orders, [])


@pytest.mark.parametrize("name", STRATEGIES)
def test_erro_sem_pedidos(graph, data, name) -> None:
    with pytest.raises(NoOrdersError, match="pedidos"):
        STRATEGIES[name](graph, [], data.couriers)


# Casos de borda ------------------------------------------------------------------------------
@pytest.mark.parametrize("name", STRATEGIES)
def test_mais_entregadores_que_pedidos(graph, data, name) -> None:
    routes = STRATEGIES[name](graph, data.orders[:2], data.couriers)
    assert len(routes) == 2  # entregadores sem pedido não geram rota
    assert sum(len(r.stops) for r in routes) == 2


@pytest.mark.parametrize("name", STRATEGIES)
def test_entregador_inativo_nao_recebe_pedido(graph, data, name) -> None:
    couriers = [*data.couriers[:3], data.couriers[3].model_copy(update={"active": False})]
    routes = STRATEGIES[name](graph, data.orders, couriers)
    assert data.couriers[3].id not in {r.courier_id for r in routes}
    assert sum(len(r.stops) for r in routes) == len(data.orders)


@pytest.mark.parametrize("name", STRATEGIES)
def test_um_entregador_recebe_todos(graph, data, name) -> None:
    solo = [Courier(id="E99", name="Entregador teste", vehicle="moto", cost_per_km=0.5)]
    routes = STRATEGIES[name](graph, data.orders, solo)
    assert len(routes) == 1
    assert len(routes[0].stops) == len(data.orders)


def test_vizinho_nao_piora_a_manual_no_dataset(graph, data) -> None:
    routes = _all_routes(graph, data)
    manual_km = sum(r.total_km for r in routes["manual"])
    nn_km = sum(r.total_km for r in routes["nearest_neighbor"])
    assert nn_km < manual_km
