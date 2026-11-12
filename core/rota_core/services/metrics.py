"""Métricas por rota, métricas agregadas por estratégia e relatório comparativo.

Todas as funções são puras e determinísticas: o mesmo conjunto de rotas sempre gera as mesmas
métricas. A única medida que varia entre execuções é ``compute_ms``, que é recebida pronta
(medida por quem executou a estratégia) e apenas copiada.

As métricas usam ``total_km`` e ``total_min`` das rotas, que sempre trazem distância e tempo
reais do caminho. Por isso funcionam igual para rotas otimizadas por ``distance_km`` ou
``time_min``.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from rota_core.domain.models import Metrics, Route, RouteMetrics, Strategy

BASELINE = Strategy.MANUAL.value

STRATEGY_LABELS: dict[str, str] = {
    Strategy.MANUAL.value: "Manual",
    Strategy.NEAREST_NEIGHBOR.value: "Vizinho mais próximo",
    Strategy.KMEANS_ASTAR.value: "K-Means + A*",
}

RANKING_KEYS: dict[str, str] = {
    "distancia": "total_km",
    "tempo": "total_min",
    "custo": "total_cost",
    "balanceamento": "balance_std",
}


def fmt_br(value: float, decimals: int = 1) -> str:
    """Número no formato brasileiro: vírgula decimal e ponto de milhar (1.234,5)."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def describe_change(gain: float | None, decimals: int = 1) -> str:
    """Texto padronizado de uma variação em relação à referência.

    ``gain`` segue a convenção das métricas: positivo = o valor diminuiu (melhor).
    Exemplos: ``58.7`` -> "redução de 58,7%"; ``-4.3`` -> "aumento de 4,3%".
    """
    if gain is None:
        return "—"
    if round(abs(gain), decimals) == 0:
        return "sem variação"
    if gain > 0:
        return f"redução de {fmt_br(gain, decimals)}%"
    return f"aumento de {fmt_br(-gain, decimals)}%"


def gain_percent(baseline: float, value: float) -> float:
    """Variação percentual de ``value`` em relação ao ``baseline``.

    Positivo = redução (o valor ficou menor, ou seja, melhor); negativo = aumento (pior).
    """
    if baseline <= 0:
        raise ValueError("baseline deve ser positivo")
    return (baseline - value) / baseline * 100


def safe_gain(baseline: float | None, value: float) -> float | None:
    """``gain_percent`` sem divisão por zero: devolve None sem baseline ou com baseline <= 0."""
    if baseline is None or baseline <= 0:
        return None
    return gain_percent(baseline, value)


def route_metrics(route: Route) -> RouteMetrics:
    """Métricas de uma rota. ETA = minutos desde a saída do depósito até chegar ao pedido."""
    etas = [s.eta_min for s in route.stops]
    return RouteMetrics(
        courier_id=route.courier_id,
        cluster_label=route.cluster_label,
        orders_count=len(route.stops),
        km=route.total_km,
        minutes=route.total_min,
        cost=route.total_cost,
        avg_eta_min=statistics.fmean(etas) if etas else 0.0,
        last_eta_min=max(etas, default=0.0),
    )


def compute_metrics(
    routes: list[Route],
    compute_ms: float = 0.0,
    baseline: Metrics | None = None,
    n_couriers: int | None = None,
) -> Metrics:
    """Métricas agregadas de uma execução.

    Args:
        routes: rotas da estratégia.
        compute_ms: tempo de execução da estratégia, em milissegundos.
        baseline: métricas da rota manual; sem ela, os ganhos ficam ``None``.
        n_couriers: entregadores disponíveis. Se informado, quem ficou sem rota entra no
            balanceamento com 0 pedidos; senão, considera só os entregadores com rota.

    Regras: lista vazia gera zeros (sem divisão por zero); ``avg_eta_min`` é a média por
    pedido (não por rota); ``balance_std`` é o desvio-padrão populacional de pedidos por
    entregador.
    """
    loads = [len(r.stops) for r in routes]
    if n_couriers is not None and n_couriers > len(loads):
        loads += [0] * (n_couriers - len(loads))
    etas = [s.eta_min for r in routes for s in r.stops]
    orders = sum(len(r.stops) for r in routes)
    total_km = sum(r.total_km for r in routes)
    total_min = sum(r.total_min for r in routes)
    total_cost = sum(r.total_cost for r in routes)

    return Metrics(
        total_km=total_km,
        total_min=total_min,
        total_cost=total_cost,
        avg_eta_min=statistics.fmean(etas) if etas else 0.0,
        max_route_min=max((r.total_min for r in routes), default=0.0),
        balance_std=statistics.pstdev(loads) if loads else 0.0,
        compute_ms=compute_ms,
        orders_count=orders,
        routes_count=len(routes),
        avg_orders_per_route=orders / len(routes) if routes else 0.0,
        gain_vs_manual_km=safe_gain(baseline and baseline.total_km, total_km),
        gain_vs_manual_min=safe_gain(baseline and baseline.total_min, total_min),
        gain_vs_manual_cost=safe_gain(baseline and baseline.total_cost, total_cost),
    )


@dataclass
class ComparisonReport:
    """Comparação entre estratégias: métricas, métricas por rota e rankings."""

    metrics: dict[str, Metrics]
    route_metrics: dict[str, list[RouteMetrics]]
    rankings: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_baseline(self) -> bool:
        return BASELINE in self.metrics

    def best(self, criterion: str) -> str:
        """Estratégia em 1º lugar no critério (distancia, tempo, custo, balanceamento)."""
        return self.rankings[criterion][0]

    def rows(self) -> list[dict[str, object]]:
        """Uma linha por estratégia, pronta para CSV."""
        rows = []
        for name, m in self.metrics.items():
            row: dict[str, object] = {"strategy": name, "label": STRATEGY_LABELS.get(name, name)}
            row.update(m.model_dump())
            for criterion, order in self.rankings.items():
                row[f"rank_{criterion}"] = order.index(name) + 1
            rows.append(row)
        return rows

    def markdown_table(self) -> str:
        """Tabela Markdown com as métricas principais e a variação em relação à rota manual.

        Variação: "redução de X%" quando a estratégia é melhor que a manual; "aumento de X%"
        quando é pior.
        """
        header = (
            "| Estratégia | km | min | R$ | ETA médio (min) | Maior rota (min) "
            "| Desvio de carga | Tempo de cálculo (ms) | km vs manual | min vs manual "
            "| R$ vs manual |\n"
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
        )
        lines = [header]
        for name, m in self.metrics.items():
            label = STRATEGY_LABELS.get(name, name)
            if name == BASELINE:
                changes = "referência | referência | referência"
            else:
                changes = " | ".join(
                    describe_change(g)
                    for g in (m.gain_vs_manual_km, m.gain_vs_manual_min, m.gain_vs_manual_cost)
                )
            lines.append(
                f"| {label} | {fmt_br(m.total_km, 2)} | {fmt_br(m.total_min)} "
                f"| {fmt_br(m.total_cost, 2)} | {fmt_br(m.avg_eta_min)} "
                f"| {fmt_br(m.max_route_min)} | {fmt_br(m.balance_std, 2)} "
                f"| {fmt_br(m.compute_ms)} | {changes} |"
            )
        return "\n".join(lines)

    def ranking_markdown(self) -> str:
        names = {
            "distancia": "Menor distância",
            "tempo": "Menor tempo",
            "custo": "Menor custo",
            "balanceamento": "Melhor balanceamento",
        }
        lines = ["| Critério | 1º | 2º | 3º |", "| --- | --- | --- | --- |"]
        for criterion, order in self.rankings.items():
            labels = [STRATEGY_LABELS.get(n, n) for n in order] + [""] * (3 - len(order))
            lines.append(f"| {names[criterion]} | " + " | ".join(labels[:3]) + " |")
        return "\n".join(lines)


def compare_strategies(
    results: dict[str, list[Route]],
    compute_times: dict[str, float],
    n_couriers: int | None = None,
) -> ComparisonReport:
    """Calcula métricas de cada estratégia, ganhos sobre a manual e rankings.

    Rankings: ordem crescente do critério (menor é melhor); empate desfeito pela ordem em que
    as estratégias aparecem em ``results``, para o resultado ser determinístico.
    """
    baseline = None
    if BASELINE in results:
        baseline = compute_metrics(
            results[BASELINE], compute_times.get(BASELINE, 0.0), n_couriers=n_couriers
        )

    metrics = {
        name: compute_metrics(
            routes,
            compute_times.get(name, 0.0),
            baseline=None if name == BASELINE else baseline,
            n_couriers=n_couriers,
        )
        for name, routes in results.items()
    }
    order = list(results)
    rankings = {
        criterion: sorted(order, key=lambda n, a=attr: (getattr(metrics[n], a), order.index(n)))
        for criterion, attr in RANKING_KEYS.items()
    }
    return ComparisonReport(
        metrics=metrics,
        route_metrics={
            name: [route_metrics(r) for r in routes] for name, routes in results.items()
        },
        rankings=rankings,
    )
