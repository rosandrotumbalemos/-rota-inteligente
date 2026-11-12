"""Linha de comando do núcleo: ``python -m rota_core <comando>``.

Comandos:
    generate-data   gera os CSVs fictícios determinísticos em data/
    validate-data   valida colunas e consistência dos CSVs
    run             executa as estratégias e mostra rotas e comparação (``--report`` gera tudo)
    report          executa as 3 estratégias e gera mapas, gráficos, comparison.csv e report.md
    benchmark       compara as estratégias em vários datasets gerados
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rota_core.algorithms.astar import SUPPORTED_WEIGHTS
from rota_core.algorithms.routing import RoutingError
from rota_core.config import get_settings
from rota_core.data.generator import generate_dataset
from rota_core.data.loaders import DataValidationError, load_dataset, validate_dataset
from rota_core.domain.models import Route, Strategy
from rota_core.reporting.report import generate_report
from rota_core.services.benchmark import run_benchmark
from rota_core.services.metrics import (
    BASELINE,
    ComparisonReport,
    compare_strategies,
    describe_change,
)
from rota_core.services.optimizer import ALL_STRATEGIES, optimize

STRATEGY_CHOICES = ["all", *ALL_STRATEGIES]
LABELS = {
    Strategy.MANUAL.value: "Manual (rodízio por ordem de chegada)",
    Strategy.NEAREST_NEIGHBOR.value: "Vizinho mais próximo",
    Strategy.KMEANS_ASTAR.value: "K-Means + A*",
}


def _cmd_generate(args: argparse.Namespace) -> int:
    paths = generate_dataset(args.data_dir, seed=args.seed)
    print(f"Dados gerados com seed={args.seed} em {args.data_dir}:")
    for name, path in paths.items():
        rows = sum(1 for _ in path.open(encoding="utf-8")) - 1
        print(f"  - {name}: {rows} linhas")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        dataset = load_dataset(args.data_dir)
    except DataValidationError as exc:
        print(f"ERRO: {exc}")
        return 1
    problems = validate_dataset(dataset)
    print(
        f"{len(dataset.nodes)} nós, {len(dataset.edges)} arestas, "
        f"{len(dataset.orders)} pedidos, {len(dataset.couriers)} entregadores"
    )
    if problems:
        for problem in problems:
            print(f"ERRO: {problem}")
        return 1
    print("Dados válidos.")
    return 0


def _print_routes(label: str, routes: list[Route], compute_ms: float) -> None:
    print(f"\n== {label} ==  ({compute_ms:.1f} ms)")
    print(
        f"{'Entregador':<11}{'Zona':>5}{'Pedidos':>8}{'km':>9}{'min':>9}{'R$':>9}"
        "  Sequência de pedidos"
    )
    for r in routes:
        seq = " > ".join(s.order_id for s in r.stops)
        zone = "-" if r.cluster_label is None else str(r.cluster_label)
        print(
            f"{r.courier_id:<11}{zone:>5}{len(r.stops):>8}{r.total_km:>9.2f}"
            f"{r.total_min:>9.1f}{r.total_cost:>9.2f}  {seq}"
        )
    print(
        f"{'TOTAL':<11}{'':>5}{sum(len(r.stops) for r in routes):>8}"
        f"{sum(r.total_km for r in routes):>9.2f}{sum(r.total_min for r in routes):>9.1f}"
        f"{sum(r.total_cost for r in routes):>9.2f}"
    )


def _print_comparison(report: ComparisonReport) -> None:
    if len(report.metrics) < 2:
        return
    print("\n== Comparação ==")
    print(
        f"{'Estratégia':<20}{'km':>9}{'min':>9}{'R$':>9}{'ETA médio':>11}"
        f"{'maior rota':>12}{'desvio':>8}  km vs manual"
    )
    for name, m in report.metrics.items():
        change = "referência" if name == BASELINE else describe_change(m.gain_vs_manual_km)
        print(
            f"{name:<20}{m.total_km:>9.2f}{m.total_min:>9.1f}{m.total_cost:>9.2f}"
            f"{m.avg_eta_min:>11.1f}{m.max_route_min:>12.1f}{m.balance_std:>8.2f}  {change}"
        )


def _load(args: argparse.Namespace):
    try:
        return load_dataset(args.data_dir)
    except DataValidationError as exc:
        print(f"ERRO: {exc}")
        return None


def _report(dataset, args: argparse.Namespace) -> int:
    artifacts = generate_report(
        dataset,
        args.output_dir,
        weight=args.weight,
        k=args.k,
        seed=args.seed,
        max_extra=args.max_extra,
        benchmark_seeds=args.benchmark_seeds,
    )
    print(f"\nResultados gerados em {artifacts.out_dir}:")
    for path in sorted(artifacts.paths.values()):
        print(f"  - {path.relative_to(artifacts.out_dir).as_posix()}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    dataset = _load(args)
    if dataset is None:
        return 1
    selected = list(ALL_STRATEGIES) if args.strategy == "all" else [args.strategy]
    print(
        f"{len(dataset.orders)} pedidos, {sum(c.active for c in dataset.couriers)} "
        f"entregadores ativos, peso de otimização: {args.weight}"
    )
    try:
        result = optimize(
            dataset,
            selected,
            weight=args.weight,
            k=args.k,
            seed=args.seed,
            max_extra=args.max_extra,
        )
    except (RoutingError, ValueError) as exc:
        print(f"ERRO: {exc}")
        return 1
    for name, routes in result.routes.items():
        _print_routes(LABELS[name], routes, result.compute_ms[name])
    n_couriers = sum(c.active for c in dataset.couriers)
    _print_comparison(compare_strategies(result.routes, result.compute_ms, n_couriers))
    if args.report:
        if args.strategy != "all":
            print("\nAviso: --report sempre gera o relatório completo com as 3 estratégias.")
        return _report(dataset, args)
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    dataset = _load(args)
    if dataset is None:
        return 1
    try:
        return _report(dataset, args)
    except (RoutingError, ValueError) as exc:
        print(f"ERRO: {exc}")
        return 1


def _cmd_benchmark(args: argparse.Namespace) -> int:
    """Roda as 3 estratégias em vários conjuntos de dados gerados (seeds 1..N)."""
    bench = run_benchmark(args.seeds, args.weight, args.k, args.seed, args.max_extra)
    print(
        f"Média de {args.seeds} conjuntos de dados gerados (seeds 1..{args.seeds}), {args.weight}:"
    )
    print(f"{'Estratégia':<20}{'km':>9}{'min':>9}{'R$':>9}{'maior rota':>12}")
    for name, a in bench.averages.items():
        print(
            f"{name:<20}{a['total_km']:>9.2f}{a['total_min']:>9.1f}"
            f"{a['total_cost']:>9.2f}{a['max_route_min']:>12.1f}"
        )
    print(
        f"\nK-Means + A* percorreu menos km que o vizinho mais próximo em "
        f"{bench.kmeans_wins_km} de {args.seeds} conjuntos "
        f"(maior rota mais curta em {bench.kmeans_wins_makespan})."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="rota_core", description="Rota Inteligente — núcleo de IA"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate-data", help="gera CSVs fictícios determinísticos")
    gen.add_argument("--seed", type=int, default=settings.seed)
    gen.add_argument("--data-dir", type=Path, default=settings.data_dir)
    gen.set_defaults(func=_cmd_generate)

    val = sub.add_parser("validate-data", help="valida colunas e consistência dos CSVs")
    val.add_argument("--data-dir", type=Path, default=settings.data_dir)
    val.set_defaults(func=_cmd_validate)

    run = sub.add_parser("run", help="executa as estratégias de roteamento")
    run.add_argument("--strategy", choices=STRATEGY_CHOICES, default="all")
    run.add_argument("--report", action="store_true", help="gera mapas, gráficos e report.md")
    run.set_defaults(func=_cmd_run)

    report = sub.add_parser("report", help="gera mapas, gráficos, comparison.csv e report.md")
    report.set_defaults(func=_cmd_report)

    bench = sub.add_parser("benchmark", help="compara as estratégias em vários datasets gerados")
    bench.add_argument("--seeds", type=int, default=30)
    bench.set_defaults(func=_cmd_benchmark)

    for cmd in (run, report):
        cmd.add_argument("--data-dir", type=Path, default=settings.data_dir)
        cmd.add_argument("--output-dir", type=Path, default=settings.outputs_dir)
        cmd.add_argument(
            "--benchmark-seeds",
            type=int,
            default=30,
            help="datasets do teste de robustez no relatório (0 = desliga)",
        )
    for cmd in (run, report, bench):
        cmd.add_argument("--weight", choices=SUPPORTED_WEIGHTS, default="distance_km")
        cmd.add_argument("--k", type=int, default=None, help="zonas (padrão: entregadores ativos)")
        cmd.add_argument("--seed", type=int, default=settings.seed, help="random_state do K-Means")
        cmd.add_argument("--max-extra", type=int, default=2, help="folga de pedidos por zona")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
