"""Testes do A* (Etapa 3): correção, otimalidade frente ao Dijkstra, heurística e erros."""

from __future__ import annotations

import random

import networkx as nx
import pytest

from rota_core.algorithms.astar import (
    SUPPORTED_WEIGHTS,
    NodeNotFoundError,
    NoPathError,
    astar_path,
    make_heuristic,
    max_speed_kmh,
)
from rota_core.config import REPO_ROOT
from rota_core.data import load_dataset
from rota_core.domain import AStarResult, Edge, Node, NodeKind
from rota_core.graph import build_city_graph, depot_id

N_RANDOM_PAIRS = 250
TOL = 1e-9


@pytest.fixture(scope="module")
def city() -> nx.DiGraph:
    """Grafo construído a partir dos CSVs versionados em data/."""
    dataset = load_dataset(REPO_ROOT / "data")
    return build_city_graph(dataset.nodes, dataset.edges)


@pytest.fixture(scope="module")
def random_pairs(city: nx.DiGraph) -> list[tuple[str, str]]:
    rng = random.Random(2026)
    nodes = sorted(city.nodes)
    return [tuple(rng.sample(nodes, 2)) for _ in range(N_RANDOM_PAIRS)]


def _node(node_id: str, lat: float, lon: float, kind: NodeKind = NodeKind.BAIRRO) -> Node:
    return Node(id=node_id, name=node_id, kind=kind, lat=lat, lon=lon)


@pytest.fixture()
def oneway_graph() -> nx.DiGraph:
    """Triângulo de mão única A -> B -> C -> A, mais um nó D isolado."""
    nodes = [
        _node("A", -23.550, -46.630, NodeKind.DEPOT),
        _node("B", -23.550, -46.620),
        _node("C", -23.540, -46.620),
        _node("D", -23.570, -46.640),
    ]
    edges = [
        Edge(source="A", target="B", distance_km=1.5, speed_kmh=30, oneway=True),
        Edge(source="B", target="C", distance_km=1.5, speed_kmh=30, oneway=True),
        Edge(source="C", target="A", distance_km=2.0, speed_kmh=30, oneway=True),
    ]
    return build_city_graph(nodes, edges)


def _edge_sum(graph: nx.DiGraph, path: list[str], weight: str) -> float:
    return sum(graph.edges[u, v][weight] for u, v in zip(path, path[1:], strict=False))


# 1. Encontra caminho entre o depósito e vários nós ---------------------------------------
@pytest.mark.parametrize("weight", SUPPORTED_WEIGHTS)
def test_encontra_caminho_do_deposito_para_todos_os_nos(city: nx.DiGraph, weight: str) -> None:
    depot = depot_id(city)
    for target in city.nodes:
        result = astar_path(city, depot, target, weight=weight)
        assert isinstance(result, AStarResult)
        assert result.path


# 2. Começa na origem e termina no destino ------------------------------------------------
def test_caminho_comeca_na_origem_e_termina_no_destino(city, random_pairs) -> None:
    for source, target in random_pairs:
        path = astar_path(city, source, target).path
        assert path[0] == source
        assert path[-1] == target


# 3. Nós consecutivos ligados por arco ----------------------------------------------------
def test_nos_consecutivos_conectados(city, random_pairs) -> None:
    for source, target in random_pairs:
        path = astar_path(city, source, target).path
        assert all(city.has_edge(u, v) for u, v in zip(path, path[1:], strict=False))
        assert len(path) == len(set(path)), "caminho ótimo não repete nós"


# 4. Custo = soma dos pesos ---------------------------------------------------------------
@pytest.mark.parametrize("weight", SUPPORTED_WEIGHTS)
def test_custo_total_e_soma_dos_pesos(city, random_pairs, weight: str) -> None:
    for source, target in random_pairs:
        r = astar_path(city, source, target, weight=weight)
        assert r.total_cost == pytest.approx(_edge_sum(city, r.path, weight))
        assert r.total_distance_km == pytest.approx(_edge_sum(city, r.path, "distance_km"))
        assert r.total_time_min == pytest.approx(_edge_sum(city, r.path, "time_min"))


# 5 e 6. Igual ao Dijkstra do NetworkX em 250 pares, para distância e tempo -----------------
@pytest.mark.parametrize("weight", SUPPORTED_WEIGHTS)
def test_igual_ao_dijkstra(city, random_pairs, weight: str) -> None:
    assert len(random_pairs) >= 200
    for source, target in random_pairs:
        expected = nx.dijkstra_path_length(city, source, target, weight=weight)
        assert astar_path(city, source, target, weight=weight).total_cost == pytest.approx(
            expected
        ), (source, target)


# 7. Heurística nunca superestima ---------------------------------------------------------
@pytest.mark.parametrize("weight", SUPPORTED_WEIGHTS)
def test_heuristica_admissivel(city: nx.DiGraph, weight: str) -> None:
    reverse = city.reverse(copy=False)
    for target in city.nodes:
        h = make_heuristic(city, target, weight)
        real = nx.single_source_dijkstra_path_length(reverse, target, weight=weight)
        for node, real_cost in real.items():
            assert h(node) <= real_cost + TOL, (node, target)
        assert h(target) == 0


@pytest.mark.parametrize("weight", SUPPORTED_WEIGHTS)
def test_heuristica_consistente(city: nx.DiGraph, weight: str) -> None:
    """Consistência (h(u) <= w(u,v) + h(v)) implica admissibilidade e evita reabrir nós."""
    for target in random.Random(7).sample(sorted(city.nodes), 10):
        h = make_heuristic(city, target, weight)
        for u, v, data in city.edges(data=True):
            assert h(u) <= data[weight] + h(v) + TOL


def test_velocidade_maxima_vem_das_arestas(city: nx.DiGraph) -> None:
    assert max_speed_kmh(city) == max(s for _, _, s in city.edges(data="speed_kmh"))


def test_astar_expande_menos_que_todos_os_nos(city, random_pairs) -> None:
    expanded = [astar_path(city, s, t).expanded_nodes for s, t in random_pairs]
    assert sum(expanded) / len(expanded) < city.number_of_nodes()


# 8. Origem ou destino inexistente --------------------------------------------------------
def test_erro_origem_inexistente(city) -> None:
    with pytest.raises(NodeNotFoundError, match="origem"):
        astar_path(city, "X99", "N01")


def test_erro_destino_inexistente(city) -> None:
    with pytest.raises(NodeNotFoundError, match="destino"):
        astar_path(city, "N00", "X99")


def test_erro_peso_invalido(city) -> None:
    with pytest.raises(ValueError, match="peso não suportado"):
        astar_path(city, "N00", "N01", weight="custo")


# 9. Sem caminho --------------------------------------------------------------------------
def test_erro_sem_caminho(oneway_graph) -> None:
    with pytest.raises(NoPathError):
        astar_path(oneway_graph, "A", "D")
    with pytest.raises(NoPathError):
        astar_path(oneway_graph, "D", "A")


# 10. Mão única ---------------------------------------------------------------------------
def test_respeita_mao_unica(oneway_graph) -> None:
    ida = astar_path(oneway_graph, "A", "C")
    assert ida.path == ["A", "B", "C"]
    assert ida.total_distance_km == pytest.approx(3.0)

    # C -> B não existe: é preciso dar a volta por A.
    volta = astar_path(oneway_graph, "C", "B")
    assert volta.path == ["C", "A", "B"]
    assert volta.total_distance_km == pytest.approx(3.5)
    assert volta.total_time_min == pytest.approx(3.5 / 30 * 60)


# Extras ----------------------------------------------------------------------------------
def test_origem_igual_ao_destino(city) -> None:
    result = astar_path(city, "N05", "N05")
    assert result.path == ["N05"]
    assert result.total_cost == 0


def test_peso_tempo_pode_escolher_caminho_mais_longo_e_mais_rapido() -> None:
    nodes = [
        _node("A", -23.550, -46.630, NodeKind.DEPOT),
        _node("B", -23.550, -46.620),
        _node("D", -23.555, -46.625),
    ]
    edges = [
        Edge(source="A", target="D", distance_km=2.0, speed_kmh=20),  # rua lenta e curta: 6 min
        Edge(source="A", target="B", distance_km=1.5, speed_kmh=60),  # avenida: 1,5 min
        Edge(source="B", target="D", distance_km=1.5, speed_kmh=60),  # avenida: 1,5 min
    ]
    graph = build_city_graph(nodes, edges)
    assert astar_path(graph, "A", "D", weight="distance_km").path == ["A", "D"]
    rapido = astar_path(graph, "A", "D", weight="time_min")
    assert rapido.path == ["A", "B", "D"]
    assert rapido.total_cost == pytest.approx(3.0)
    assert rapido.total_distance_km == pytest.approx(3.0)
