"""Testes da estratégia principal: K-Means, balanceamento, atribuição húngara, 2-opt e rotas."""

from __future__ import annotations

import itertools
import random
from collections import Counter
from datetime import datetime

import networkx as nx
import pytest

from rota_core.algorithms.assignment import (
    AssignmentError,
    assign_zones,
    snap_orders_to_nodes,
    zone_cost_matrix,
)
from rota_core.algorithms.kmeans_astar import kmeans_astar_plan, kmeans_astar_routes
from rota_core.algorithms.kmeans_zones import (
    ClusteringError,
    balance_zones,
    cluster_orders,
    project_km,
    zone_capacity,
)
from rota_core.algorithms.nearest_neighbor import nearest_neighbor_routes
from rota_core.algorithms.routing import NoActiveCouriersError, NoOrdersError, RoutingError
from rota_core.algorithms.two_opt import tour_cost, two_opt
from rota_core.cli import main
from rota_core.config import REPO_ROOT
from rota_core.data import load_dataset
from rota_core.domain import Courier, Order, Strategy, Zone
from rota_core.graph import build_city_graph, depot_id, haversine_km

WEIGHTS = ("distance_km", "time_min")


@pytest.fixture(scope="module")
def data():
    return load_dataset(REPO_ROOT / "data")


@pytest.fixture()
def graph(data) -> nx.DiGraph:
    return build_city_graph(data.nodes, data.edges)


@pytest.fixture()
def snapped(graph, data) -> list[Order]:
    return snap_orders_to_nodes(graph, data.orders)


def _order(order_id: str, lat: float, lon: float) -> Order:
    return Order(
        id=order_id,
        code=f"SE-{order_id}",
        customer_alias="Cliente teste",
        address_label="Endereço fictício",
        lat=lat,
        lon=lon,
        created_at=datetime(2026, 11, 12, 12, 0),
        value=40,
    )


def _courier(courier_id: str, cost: float) -> Courier:
    return Courier(id=courier_id, name=courier_id, vehicle="moto", cost_per_km=cost)


# --- Projeção e K-Means ------------------------------------------------------------------
def test_projecao_em_km_preserva_distancia() -> None:
    a, b = (-23.5505, -46.6333), (-23.5614, -46.6559)
    ax, ay = project_km(*a, ref_lat=-23.555)
    bx, by = project_km(*b, ref_lat=-23.555)
    assert ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 == pytest.approx(haversine_km(*a, *b), rel=0.01)


def test_kmeans_cada_pedido_em_uma_zona(snapped) -> None:
    zones = cluster_orders(snapped, k=4)
    assert len(zones) == 4
    ids = [oid for z in zones for oid in z.order_ids]
    assert sorted(ids) == sorted(o.id for o in snapped)
    assert all(z.size > 0 for z in zones)
    assert [z.cluster_id for z in zones] == [0, 1, 2, 3]


def test_kmeans_deterministico(snapped) -> None:
    first = [z.order_ids for z in cluster_orders(snapped, k=4, seed=42)]
    second = [z.order_ids for z in cluster_orders(snapped, k=4, seed=42)]
    assert first == second


def test_kmeans_separa_grupos_obvios() -> None:
    west = [_order(f"W{i}", -23.55 + i * 0.001, -46.66) for i in range(4)]
    east = [_order(f"E{i}", -23.55 + i * 0.001, -46.60) for i in range(4)]
    zones = cluster_orders([*east, *west], k=2)
    assert {frozenset(z.order_ids) for z in zones} == {
        frozenset(o.id for o in west),
        frozenset(o.id for o in east),
    }
    assert zones[0].centroid_lon < zones[1].centroid_lon  # numeradas de oeste para leste


def test_kmeans_centroide_e_media_dos_pedidos(snapped) -> None:
    for zone in cluster_orders(snapped, k=4):
        assert zone.centroid_lat == pytest.approx(sum(o.lat for o in zone.orders) / zone.size)
        assert zone.centroid_lon == pytest.approx(sum(o.lon for o in zone.orders) / zone.size)


def test_kmeans_k_maior_que_pontos_distintos() -> None:
    same = [_order(f"P{i}", -23.55, -46.63) for i in range(3)]
    zones = cluster_orders(same, k=4)
    assert len(zones) == 1  # 1 coordenada distinta -> 1 zona, sem zona vazia
    assert zones[0].size == 3


def test_kmeans_erros() -> None:
    with pytest.raises(ClusteringError):
        cluster_orders([], k=2)
    with pytest.raises(ClusteringError):
        cluster_orders([_order("P1", -23.55, -46.63)], k=0)


# --- Balanceamento -----------------------------------------------------------------------
def _zone(cid: int, orders: list[Order]) -> Zone:
    lat = sum(o.lat for o in orders) / len(orders)
    lon = sum(o.lon for o in orders) / len(orders)
    return Zone(cluster_id=cid, centroid_lat=lat, centroid_lon=lon, orders=orders)


def test_capacidade() -> None:
    assert zone_capacity(20, 4, max_extra=2) == 7
    assert zone_capacity(21, 4, max_extra=0) == 6


@pytest.mark.parametrize("max_extra", [0, 1, 2])
def test_balanceamento_respeita_limite_sem_zona_vazia(max_extra) -> None:
    crowded = [_order(f"A{i:02d}", -23.55 + i * 0.0005, -46.65) for i in range(14)]
    small = [_order("B00", -23.55, -46.60)]
    tiny = [_order("C00", -23.53, -46.62)]
    zones = balance_zones([_zone(0, crowded), _zone(1, small), _zone(2, tiny)], max_extra)
    cap = zone_capacity(16, 3, max_extra)
    assert all(0 < z.size <= cap for z in zones)
    assert Counter(oid for z in zones for oid in z.order_ids) == Counter(
        o.id for o in [*crowded, *small, *tiny]
    )


def test_balanceamento_sem_mudanca_quando_ja_equilibrado(snapped) -> None:
    zones = cluster_orders(snapped, k=4)
    relaxed = balance_zones(zones, max_extra=20)
    assert [z.order_ids for z in relaxed] == [z.order_ids for z in zones]


def test_balanceamento_move_pedidos_de_borda() -> None:
    core = [_order(f"A{i}", -23.55, -46.65 + i * 0.0001) for i in range(5)]
    edge = _order("A9", -23.55, -46.62)  # mais perto da zona leste
    east = [_order("B0", -23.55, -46.60)]
    zones = balance_zones([_zone(0, [*core, edge]), _zone(1, east)], max_extra=1)
    assert "A9" in zones[1].order_ids  # 6 -> cap 5: sai o pedido mais próximo da vizinha


def test_balanceamento_dataset_oficial(snapped) -> None:
    zones = balance_zones(cluster_orders(snapped, k=4), max_extra=2)
    assert max(z.size for z in zones) <= 7
    assert min(z.size for z in zones) >= 1


# --- Atribuição húngara ------------------------------------------------------------------
def test_hungaro_e_otimo_contra_forca_bruta() -> None:
    rng = random.Random(3)
    zones = [_zone(i, [_order(f"P{i}", -23.55, -46.63)]) for i in range(4)]
    couriers = [_courier(f"E{j}", round(rng.uniform(0.1, 0.6), 2)) for j in range(4)]
    zone_km = {i: rng.uniform(5, 40) for i in range(4)}
    result = assign_zones(zones, couriers, zone_km)
    matrix = zone_cost_matrix(zones, couriers, zone_km)
    cost = sum(matrix[cid][[c.id for c in couriers].index(cour)] for cid, cour in result.items())
    best = min(sum(matrix[i][p[i]] for i in range(4)) for p in itertools.permutations(range(4)))
    assert cost == pytest.approx(best)
    assert len(set(result.values())) == 4  # entregadores distintos


def test_hungaro_maior_zona_para_menor_custo_por_km() -> None:
    zones = [_zone(i, [_order(f"P{i}", -23.55, -46.63)]) for i in range(2)]
    couriers = [_courier("MOTO", 0.50), _courier("BIKE", 0.10)]
    assert assign_zones(zones, couriers, {0: 30.0, 1: 5.0}) == {0: "BIKE", 1: "MOTO"}


def test_hungaro_mais_entregadores_que_zonas() -> None:
    zones = [_zone(0, [_order("P0", -23.55, -46.63)])]
    result = assign_zones(zones, [_courier("E1", 0.4), _courier("E2", 0.2)], {0: 10})
    assert result == {0: "E2"}


def test_hungaro_erros() -> None:
    zones = [_zone(i, [_order(f"P{i}", -23.55, -46.63)]) for i in range(3)]
    with pytest.raises(AssignmentError, match="zonas para"):
        assign_zones(zones, [_courier("E1", 0.4)], {0: 1, 1: 1, 2: 1})
    with pytest.raises(AssignmentError):
        assign_zones([], [_courier("E1", 0.4)], {})


# --- 2-opt -------------------------------------------------------------------------------
def _euclid(points: dict[str, tuple[float, float]]):
    def cost(a: str, b: str) -> float:
        (ax, ay), (bx, by) = points[a], points[b]
        return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5

    return cost


def test_two_opt_desfaz_cruzamento() -> None:
    points = {"D": (0, 0), "A": (0, 1), "B": (1, 1), "C": (1, 0)}
    cost = _euclid(points)
    crossed = ["B", "A", "C"]  # D->B->A->C->D cruza
    improved = two_opt(crossed, cost, "D")
    assert tour_cost(improved, cost, "D") == pytest.approx(4.0)
    assert tour_cost(improved, cost, "D") < tour_cost(crossed, cost, "D")


def test_two_opt_nunca_piora_em_rotas_aleatorias() -> None:
    rng = random.Random(11)
    for _ in range(200):
        n = rng.randint(0, 8)
        points = {"D": (0.0, 0.0)} | {f"P{i}": (rng.random(), rng.random()) for i in range(n)}
        cost = _euclid(points)
        seq = [p for p in points if p != "D"]
        rng.shuffle(seq)
        improved = two_opt(seq, cost, "D")
        assert sorted(improved) == sorted(seq)
        assert tour_cost(improved, cost, "D") <= tour_cost(seq, cost, "D") + 1e-12


def test_two_opt_nunca_piora_com_custo_assimetrico() -> None:
    rng = random.Random(5)
    nodes = ["D", *[f"P{i}" for i in range(6)]]
    table = {(a, b): rng.uniform(1, 10) for a in nodes for b in nodes if a != b}

    def cost(a: str, b: str) -> float:
        return 0.0 if a == b else table[a, b]

    for _ in range(100):
        seq = nodes[1:]
        rng.shuffle(seq)
        assert tour_cost(two_opt(seq, cost, "D"), cost, "D") <= tour_cost(seq, cost, "D")


def test_two_opt_casos_triviais() -> None:
    cost = _euclid({"D": (0, 0), "A": (1, 0)})
    assert two_opt([], cost, "D") == []
    assert two_opt(["A"], cost, "D") == ["A"]


@pytest.mark.parametrize("weight", WEIGHTS)
def test_two_opt_no_plano_nunca_piora(graph, data, weight) -> None:
    plan = kmeans_astar_plan(graph, data.orders, data.couriers, weight=weight)
    for cid, final in plan.final_cost.items():
        assert final <= plan.initial_cost[cid] + 1e-9
        assert sorted(o.id for o in plan.sequences[cid]) == sorted(
            o.id for o in plan.initial_sequences[cid]
        )


# --- Rota final --------------------------------------------------------------------------
@pytest.mark.parametrize("weight", WEIGHTS)
def test_rotas_validas(graph, data, weight) -> None:
    routes = kmeans_astar_routes(graph, data.orders, data.couriers, weight=weight)
    depot = depot_id(graph)
    for route in routes:
        assert route.strategy == Strategy.KMEANS_ASTAR
        assert route.cluster_label is not None
        assert route.path[0] == depot
        assert route.path[-1] == depot
        assert all(graph.has_edge(u, v) for u, v in zip(route.path, route.path[1:], strict=False))
        assert route.total_km >= 0
        assert route.total_min >= 0


@pytest.mark.parametrize("weight", WEIGHTS)
def test_cada_pedido_exatamente_uma_vez(graph, data, weight) -> None:
    routes = kmeans_astar_routes(graph, data.orders, data.couriers, weight=weight)
    counts = Counter(s.order_id for r in routes for s in r.stops)
    assert set(counts) == {o.id for o in data.orders}
    assert all(c == 1 for c in counts.values())


def test_uma_zona_por_entregador(graph, data) -> None:
    plan = kmeans_astar_plan(graph, data.orders, data.couriers)
    assert len(plan.routes) == len(plan.zones) == 4
    assert len({r.courier_id for r in plan.routes}) == 4
    for route in plan.routes:
        zone = next(z for z in plan.zones if z.cluster_id == route.cluster_label)
        assert sorted(s.order_id for s in route.stops) == sorted(zone.order_ids)
        assert plan.assignment[route.cluster_label] == route.courier_id


def test_custo_e_totais(graph, data) -> None:
    cost_per_km = {c.id: c.cost_per_km for c in data.couriers}
    plan = kmeans_astar_plan(graph, data.orders, data.couriers)
    for route in plan.routes:
        edges = list(zip(route.path, route.path[1:], strict=False))
        assert route.total_km == pytest.approx(sum(graph.edges[e]["distance_km"] for e in edges))
        assert route.total_km == pytest.approx(plan.zone_km[route.cluster_label])
        assert route.total_cost == pytest.approx(route.total_km * cost_per_km[route.courier_id])


def test_estrategia_deterministica(graph, data) -> None:
    def signature() -> list[tuple[str, list[str]]]:
        routes = kmeans_astar_routes(graph, data.orders, data.couriers)
        return [(r.courier_id, [s.order_id for s in r.stops]) for r in routes]

    assert signature() == signature()


def test_k_menor_que_entregadores(graph, data) -> None:
    routes = kmeans_astar_routes(graph, data.orders, data.couriers, k=2)
    assert len(routes) == 2
    assert sum(len(r.stops) for r in routes) == len(data.orders)


def test_erros(graph, data) -> None:
    with pytest.raises(RoutingError, match="k=5"):
        kmeans_astar_routes(graph, data.orders, data.couriers, k=5)
    with pytest.raises(NoOrdersError):
        kmeans_astar_routes(graph, [], data.couriers)
    inactive = [c.model_copy(update={"active": False}) for c in data.couriers]
    with pytest.raises(NoActiveCouriersError):
        kmeans_astar_routes(graph, data.orders, inactive)


def test_nao_altera_cache_das_outras_estrategias(graph, data) -> None:
    """Rodar o K-Means antes não muda o resultado do vizinho mais próximo (comparação justa)."""
    before = nearest_neighbor_routes(
        build_city_graph(data.nodes, data.edges), data.orders, data.couriers
    )
    kmeans_astar_routes(graph, data.orders, data.couriers)
    after = nearest_neighbor_routes(graph, data.orders, data.couriers)
    assert [r.total_km for r in before] == pytest.approx([r.total_km for r in after])


# --- CLI ---------------------------------------------------------------------------------
def test_cli_run_kmeans(capsys) -> None:
    assert main(["run", "--strategy", "kmeans_astar"]) == 0
    out = capsys.readouterr().out
    assert "K-Means + A*" in out
    assert "TOTAL" in out


def test_cli_run_all_mostra_comparacao(capsys) -> None:
    assert main(["run", "--strategy", "all"]) == 0
    out = capsys.readouterr().out
    assert "Comparação" in out
    assert "kmeans_astar" in out


def test_cli_k_invalido(capsys) -> None:
    assert main(["run", "--strategy", "kmeans_astar", "--k", "9"]) == 1
    assert "ERRO" in capsys.readouterr().out


def test_cli_benchmark(capsys) -> None:
    assert main(["benchmark", "--seeds", "2"]) == 0
    assert "de 2 conjuntos" in capsys.readouterr().out
