"""Verificações rápidas de que cada algoritmo existe e responde. Os testes detalhados estão em
``test_astar.py``, ``test_baselines.py`` e ``test_kmeans_astar.py``."""

from __future__ import annotations

import pytest

from rota_core.algorithms import assignment, astar, kmeans_zones, manual, nearest_neighbor, two_opt
from rota_core.cli import main


def _stage5_checks(dataset) -> dict[str, bool]:
    from rota_core.domain import Zone

    zones = kmeans_zones.cluster_orders(dataset.orders, 4)

    def dist(a: int, b: int) -> float:
        return abs(a - b)

    seq = two_opt.two_opt([3, 1, 2], dist, 0)
    plan = assignment.assign_zones([Zone(0, 0, 0, dataset.orders[:1])], dataset.couriers, {0: 1.0})
    return {
        "cluster_orders": len(zones) == 4,
        "two_opt": two_opt.tour_cost(seq, dist, 0) == 6,
        "assign_zones": len(plan) == 1,
    }


@pytest.mark.parametrize("name", ["cluster_orders", "two_opt", "assign_zones"])
def test_algoritmos_da_etapa5_implementados(dataset, name) -> None:
    assert _stage5_checks(dataset)[name]


def test_astar_implementado(dataset) -> None:
    from rota_core.graph import build_city_graph

    graph = build_city_graph(dataset.nodes, dataset.edges)
    result = astar.astar_path(graph, "N00", "N01")
    assert result.path[0] == "N00"
    assert result.path[-1] == "N01"


@pytest.mark.parametrize(
    "strategy", [manual.manual_routes, nearest_neighbor.nearest_neighbor_routes]
)
def test_baselines_implementados(dataset, strategy) -> None:
    from rota_core.graph import build_city_graph

    graph = build_city_graph(dataset.nodes, dataset.edges)
    routes = strategy(graph, dataset.orders, dataset.couriers)
    assert sum(len(r.stops) for r in routes) == len(dataset.orders)


def test_cli_run_all_executa_as_tres_estrategias(capsys) -> None:
    assert main(["run", "--strategy", "all"]) == 0
    out = capsys.readouterr().out
    for label in ("Manual", "Vizinho mais próximo", "K-Means + A*"):
        assert label in out


def test_cli_validate_data_ok(repo_data_dir, capsys) -> None:
    assert main(["validate-data", "--data-dir", str(repo_data_dir)]) == 0
    assert "Dados válidos" in capsys.readouterr().out


def test_cli_generate_data(tmp_path, capsys) -> None:
    assert main(["generate-data", "--data-dir", str(tmp_path), "--seed", "42"]) == 0
    assert (tmp_path / "nodes.csv").exists()
    assert "nodes.csv: 40 linhas" in capsys.readouterr().out
