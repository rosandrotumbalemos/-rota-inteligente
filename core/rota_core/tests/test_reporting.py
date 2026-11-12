"""Testes do Bloco 2: métricas, comparação, mapas, gráficos, relatório e comandos do CLI."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import matplotlib.image as mpimg
import pytest

from rota_core.algorithms.assignment import snap_orders_to_nodes
from rota_core.algorithms.kmeans_zones import evaluate_k
from rota_core.cli import main
from rota_core.config import REPO_ROOT
from rota_core.data import load_dataset
from rota_core.domain import Metrics, Route, RouteStop, Strategy
from rota_core.graph import build_city_graph
from rota_core.reporting.report import generate_report, zone_access
from rota_core.services.benchmark import run_benchmark
from rota_core.services.metrics import (
    compare_strategies,
    compute_metrics,
    describe_change,
    fmt_br,
    route_metrics,
    safe_gain,
)
from rota_core.services.optimizer import ALL_STRATEGIES, optimize

MAPS = [
    "graph_map",
    "zones_map",
    "routes_manual",
    "routes_nearest_neighbor",
    "routes_kmeans_astar",
    "comparison_map",
]
CHARTS = [
    "distance_comparison",
    "time_comparison",
    "cost_comparison",
    "route_load",
    "execution_time",
    "kmeans_elbow",
    "kmeans_silhouette",
]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module")
def data():
    return load_dataset(REPO_ROOT / "data")


@pytest.fixture(scope="module")
def artifacts(data, tmp_path_factory):
    """Relatório completo gerado uma vez numa pasta temporária (benchmark curto)."""
    return generate_report(data, tmp_path_factory.mktemp("outputs"), benchmark_seeds=2)


def _route(
    courier: str,
    etas: list[float],
    km: float,
    minutes: float,
    cost: float,
    strategy: Strategy = Strategy.KMEANS_ASTAR,
) -> Route:
    stops = [
        RouteStop(order_id=f"{courier}-{i}", node_id="N01", seq=i, eta_min=eta, cumulative_km=0)
        for i, eta in enumerate(etas, start=1)
    ]
    return Route(
        courier_id=courier,
        strategy=strategy,
        stops=stops,
        path=["N00", "N01", "N00"],
        total_km=km,
        total_min=minutes,
        total_cost=cost,
    )


# --- Métricas ----------------------------------------------------------------------------
def test_compute_metrics_valores_corretos() -> None:
    routes = [
        _route("E01", [10, 20, 30], km=12, minutes=40, cost=6),
        _route("E02", [5], km=8, minutes=20, cost=4),
    ]
    m = compute_metrics(routes, compute_ms=7.5)
    assert m.total_km == 20
    assert m.total_min == 60
    assert m.total_cost == 10
    assert m.avg_eta_min == pytest.approx((10 + 20 + 30 + 5) / 4)  # média por pedido
    assert m.max_route_min == 40
    assert m.balance_std == pytest.approx(1.0)  # cargas 3 e 1
    assert m.compute_ms == 7.5
    assert m.orders_count == 4
    assert m.routes_count == 2
    assert m.avg_orders_per_route == 2
    assert m.gain_vs_manual_km is None


def test_compute_metrics_ganhos_sobre_manual() -> None:
    manual = compute_metrics([_route("E01", [10], km=100, minutes=200, cost=50)])
    better = compute_metrics([_route("E01", [5], km=60, minutes=150, cost=55)], baseline=manual)
    assert better.gain_vs_manual_km == pytest.approx(40)
    assert better.gain_vs_manual_min == pytest.approx(25)
    assert better.gain_vs_manual_cost == pytest.approx(-10)  # custo maior que o da manual: aumento


def test_sem_divisao_por_zero() -> None:
    zero = compute_metrics([_route("E01", [], km=0, minutes=0, cost=0)])
    m = compute_metrics([_route("E01", [3], km=5, minutes=9, cost=1)], baseline=zero)
    assert m.gain_vs_manual_km is None
    assert safe_gain(None, 3) is None
    assert safe_gain(0, 3) is None
    empty = compute_metrics([])
    assert (empty.avg_eta_min, empty.avg_orders_per_route, empty.balance_std) == (0, 0, 0)


def test_balanceamento_conta_entregadores_sem_rota() -> None:
    routes = [_route("E01", [1, 2], km=1, minutes=1, cost=1)]
    assert compute_metrics(routes).balance_std == 0
    assert compute_metrics(routes, n_couriers=2).balance_std == pytest.approx(1.0)  # 2 e 0


def test_route_metrics() -> None:
    rm = route_metrics(_route("E07", [4, 8], km=3, minutes=12, cost=1.5))
    assert (rm.courier_id, rm.orders_count, rm.km, rm.minutes, rm.cost) == ("E07", 2, 3, 12, 1.5)
    assert rm.avg_eta_min == 6
    assert rm.last_eta_min == 8


def test_metrics_deterministicas(data) -> None:
    first = optimize(data)
    second = optimize(data)
    a = compare_strategies(first.routes, {}).metrics
    b = compare_strategies(second.routes, {}).metrics
    assert a == b


@pytest.mark.parametrize("weight", ["distance_km", "time_min"])
def test_metrics_para_os_dois_pesos(data, weight) -> None:
    run = optimize(data, weight=weight)
    report = compare_strategies(run.routes, run.compute_ms, n_couriers=4)
    for name, m in report.metrics.items():
        assert m.orders_count == len(data.orders)
        assert m.total_km == pytest.approx(sum(r.total_km for r in run.routes[name]))
        assert m.compute_ms > 0
    assert report.metrics["manual"].gain_vs_manual_km is None
    assert report.metrics["kmeans_astar"].gain_vs_manual_km is not None


# --- Comparação --------------------------------------------------------------------------
def test_compare_rankings_e_tabela(data) -> None:
    run = optimize(data)
    report = compare_strategies(run.routes, run.compute_ms)
    for criterion, attr in {
        "distancia": "total_km",
        "tempo": "total_min",
        "custo": "total_cost",
        "balanceamento": "balance_std",
    }.items():
        values = [getattr(report.metrics[n], attr) for n in report.rankings[criterion]]
        assert values == sorted(values)
        assert set(report.rankings[criterion]) == set(ALL_STRATEGIES)
    table = report.markdown_table().splitlines()
    assert len(table) == 2 + 3
    assert table[2].startswith("| Manual |") and "referência" in table[2]
    assert len(report.rows()) == 3


def test_compare_sem_rota_manual(data) -> None:
    run = optimize(data, strategies=["nearest_neighbor", "kmeans_astar"])
    report = compare_strategies(run.routes, run.compute_ms)
    assert not report.has_baseline
    for m in report.metrics.values():
        assert m.gain_vs_manual_km is None
        assert m.gain_vs_manual_min is None
        assert m.gain_vs_manual_cost is None
    assert "—" in report.markdown_table()
    assert report.best("distancia") in {"nearest_neighbor", "kmeans_astar"}


def test_compare_empate_deterministico() -> None:
    same = [_route("E01", [1], km=10, minutes=10, cost=1)]
    report = compare_strategies({"b": same, "a": same}, {})
    assert report.rankings["distancia"] == ["b", "a"]  # empate: ordem de entrada


# --- Optimizer, k e benchmark --------------------------------------------------------------
def test_optimizer_mede_tempo_e_valida(data) -> None:
    run = optimize(data)
    assert list(run.routes) == list(ALL_STRATEGIES)
    assert all(ms > 0 for ms in run.compute_ms.values())
    assert run.kmeans_plan is not None
    with pytest.raises(ValueError, match="desconhecida"):
        optimize(data, strategies=["genetico"])


def test_ordem_de_execucao_nao_muda_resultado(data) -> None:
    forward = optimize(data, strategies=list(ALL_STRATEGIES))
    backward = optimize(data, strategies=list(reversed(ALL_STRATEGIES)))
    for name in ALL_STRATEGIES:
        assert [r.total_km for r in forward.routes[name]] == [
            r.total_km for r in backward.routes[name]
        ]


def test_evaluate_k(data) -> None:
    graph = build_city_graph(data.nodes, data.edges)
    result = evaluate_k(snap_orders_to_nodes(graph, data.orders), range(2, 9))
    assert [r["k"] for r in result] == list(range(2, 9))
    inertia = [r["inertia"] for r in result]
    assert inertia == sorted(inertia, reverse=True)  # cai com k maior
    assert all(-1 <= r["silhouette"] <= 1 for r in result)


def test_benchmark() -> None:
    assert run_benchmark(seeds=0).averages == {}
    bench = run_benchmark(seeds=2)
    assert set(bench.averages) == set(ALL_STRATEGIES)
    assert 0 <= bench.kmeans_wins_km <= 2


def test_zone_access(data) -> None:
    access = zone_access(optimize(data))
    assert len(access) == 4
    for a in access.values():
        assert a["road_km"] >= a["straight_km"] - 1e-9  # rua nunca é mais curta que a reta


# --- Arquivos gerados --------------------------------------------------------------------
def _check_png(path: Path, min_width: int = 1000) -> None:
    assert path.exists(), path
    assert path.read_bytes()[:8] == PNG_SIGNATURE
    height, width = mpimg.imread(path).shape[:2]
    assert width >= min_width, f"{path.name}: {width}px"  # alta resolução (200 dpi)
    assert height >= 600


@pytest.mark.parametrize("name", MAPS)
def test_mapas_gerados(artifacts, name) -> None:
    path = artifacts.paths[name]
    assert path.parent.name == "maps"
    assert path.name == f"{name}.png"
    _check_png(path)


@pytest.mark.parametrize("name", CHARTS)
def test_graficos_gerados(artifacts, name) -> None:
    path = artifacts.paths[name]
    assert path.parent.name == "charts"
    assert path.name == f"{name}.png"
    _check_png(path)


def test_comparison_csv(artifacts) -> None:
    with artifacts.paths["comparison_csv"].open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["strategy"] for r in rows] == list(ALL_STRATEGIES)
    for column in ("total_km", "avg_eta_min", "gain_vs_manual_km", "rank_distancia"):
        assert column in rows[0]
    assert rows[0]["gain_vs_manual_km"] == ""  # a manual não tem ganho sobre si mesma
    assert float(rows[1]["total_km"]) > 0


REQUIRED_SECTIONS = [
    "## 1. Objetivo",
    "## 2. Metodologia",
    "## 3. O grafo",
    "## 4. Os dados",
    "## 5. Algoritmos",
    "**A\\***",
    "**K-Means**",
    "**Balanceamento**",
    "**Atribuição húngara**",
    "2-opt",
    "### Tabela comparativa",
    "## 7. Interpretação",
    "## 8. Mapas",
    "## 9. Gráficos",
    "## 10. Limitações",
    "## 11. Sugestões de melhoria",
]


def test_report_md_completo(artifacts) -> None:
    text = artifacts.paths["report"].read_text(encoding="utf-8")
    for section in REQUIRED_SECTIONS:
        assert section in text, section
    links = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    assert len(links) == len(MAPS) + len(CHARTS)
    for link in links:
        assert (artifacts.out_dir / link).exists(), link
    assert "malha viária" in text


def test_report_interpretacao_honesta(artifacts) -> None:
    text = artifacts.paths["report"].read_text(encoding="utf-8")
    m = artifacts.comparison.metrics
    if m["kmeans_astar"].total_km >= m["nearest_neighbor"].total_km:
        assert "é o melhor em distância" not in text
        assert "empatam" in text or "perde" in text
    if m["kmeans_astar"].max_route_min > m["nearest_neighbor"].max_route_min:
        assert "rota mais longa é pior no K-Means" in text
    assert "não em todos os casos" in text


# --- CLI ---------------------------------------------------------------------------------
def test_cli_report(tmp_path, capsys) -> None:
    assert main(["report", "--output-dir", str(tmp_path), "--benchmark-seeds", "0"]) == 0
    out = capsys.readouterr().out
    assert "report.md" in out
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "comparison.csv").exists()
    assert len(list((tmp_path / "maps").glob("*.png"))) == len(MAPS)
    assert len(list((tmp_path / "charts").glob("*.png"))) == len(CHARTS)
    assert "Benchmark desativado" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_cli_run_report(tmp_path, capsys) -> None:
    args = [
        "run",
        "--strategy",
        "all",
        "--report",
        "--output-dir",
        str(tmp_path),
        "--benchmark-seeds",
        "0",
    ]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Comparação" in out
    assert "Resultados gerados" in out
    assert (tmp_path / "report.md").exists()
    assert len(list(tmp_path.rglob("*.png"))) == len(MAPS) + len(CHARTS)


def test_cli_report_dados_invalidos(tmp_path, capsys) -> None:
    assert main(["report", "--data-dir", str(tmp_path), "--output-dir", str(tmp_path)]) == 1
    assert "ERRO" in capsys.readouterr().out


def test_metrics_modelo_aceita_campos_antigos() -> None:
    m = Metrics(
        total_km=1,
        total_min=1,
        total_cost=1,
        avg_eta_min=1,
        max_route_min=1,
        balance_std=0,
        compute_ms=1,
    )
    assert m.orders_count == 0
    assert m.gain_vs_manual_km is None


def test_route_sem_paradas_tem_metricas_zeradas() -> None:
    rm = route_metrics(_route("E01", [], km=0, minutes=0, cost=0, strategy=Strategy.MANUAL))
    assert rm.avg_eta_min == 0
    assert rm.last_eta_min == 0


# --- Linguagem padronizada dos resultados ---------------------------------------------------
def test_describe_change() -> None:
    assert describe_change(58.68) == "redução de 58,7%"
    assert describe_change(-4.3) == "aumento de 4,3%"
    assert describe_change(0.01) == "sem variação"
    assert describe_change(None) == "—"


def test_fmt_br() -> None:
    assert fmt_br(176.706, 2) == "176,71"
    assert fmt_br(1234.5) == "1.234,5"


def test_textos_sem_ganho_negativo_nem_superioridade_absoluta(artifacts) -> None:
    text = artifacts.paths["report"].read_text(encoding="utf-8")
    table = artifacts.comparison.markdown_table()
    for content in (text, table):
        assert "ganho negativo" not in content.lower()
        assert not re.search(r"[+-]\d+[.,]\d%", content)  # sem "+58.7%" / "-4.3%"
    for claim in ("sempre melhor", "melhor em todos", "superior em todos", "sempre vence"):
        assert claim not in text.lower()
    assert "redução de" in text
