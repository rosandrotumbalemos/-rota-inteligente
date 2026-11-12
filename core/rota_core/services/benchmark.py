"""Teste de robustez: compara as estratégias em vários datasets gerados com seeds diferentes.

Um único dataset pode favorecer uma estratégia por acaso. O benchmark gera ``n`` cidades e
conjuntos de pedidos diferentes (seeds 1..n), roda as três estratégias em cada um e devolve
as médias e o número de vitórias do K-Means + A* sobre o vizinho mais próximo.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from rota_core.data.generator import generate_dataset
from rota_core.data.loaders import load_dataset
from rota_core.domain.models import Strategy
from rota_core.services.metrics import compare_strategies
from rota_core.services.optimizer import ALL_STRATEGIES, optimize

AVERAGED = ("total_km", "total_min", "total_cost", "max_route_min", "avg_eta_min", "balance_std")


@dataclass
class BenchmarkResult:
    seeds: int
    weight: str
    averages: dict[str, dict[str, float]] = field(default_factory=dict)
    kmeans_wins_km: int = 0
    kmeans_wins_makespan: int = 0


def run_benchmark(
    seeds: int = 30,
    weight: str = "distance_km",
    k: int | None = None,
    seed: int = 42,
    max_extra: int = 2,
) -> BenchmarkResult:
    """Roda as três estratégias nos datasets das seeds 1..``seeds``."""
    result = BenchmarkResult(seeds=seeds, weight=weight)
    if seeds <= 0:
        return result
    sums = {name: dict.fromkeys(AVERAGED, 0.0) for name in ALL_STRATEGIES}
    nn, km = Strategy.NEAREST_NEIGHBOR.value, Strategy.KMEANS_ASTAR.value
    for data_seed in range(1, seeds + 1):
        with tempfile.TemporaryDirectory() as tmp:
            generate_dataset(Path(tmp), seed=data_seed)
            dataset = load_dataset(Path(tmp))
        run = optimize(dataset, weight=weight, k=k, seed=seed, max_extra=max_extra)
        metrics = compare_strategies(run.routes, run.compute_ms).metrics
        for name in ALL_STRATEGIES:
            for key in AVERAGED:
                sums[name][key] += getattr(metrics[name], key)
        result.kmeans_wins_km += metrics[km].total_km < metrics[nn].total_km
        result.kmeans_wins_makespan += metrics[km].max_route_min < metrics[nn].max_route_min
    result.averages = {
        name: {key: value / seeds for key, value in values.items()} for name, values in sums.items()
    }
    return result
