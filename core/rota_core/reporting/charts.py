"""Gráficos comparativos (matplotlib). Arquivos gerados em ``<outputs>/charts``:

- ``distance_comparison.png``, ``time_comparison.png``, ``cost_comparison.png``: barras por
  estratégia, com o valor escrito em cada barra e a variação (redução ou aumento) em relação à
  rota manual.
- ``route_load.png``: pedidos e minutos por entregador, em cada estratégia.
- ``execution_time.png``: tempo de cálculo de cada estratégia (ms).
- ``kmeans_elbow.png`` e ``kmeans_silhouette.png``: avaliação de k = 2..8.

Regras visuais: um único eixo y por gráfico, valores escritos nas barras (a cor nunca é a
única identificação), grade discreta.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes

from rota_core.reporting.style import (
    STRATEGY_COLORS,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    apply_style,
    clean_axes,
    save,
)
from rota_core.services.metrics import (
    BASELINE,
    STRATEGY_LABELS,
    ComparisonReport,
    describe_change,
    fmt_br,
)


def _title(ax: Axes, title: str, subtitle: str) -> None:
    ax.set_title(title, loc="left", pad=20)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=8, color=TEXT_SECONDARY)


def _strategy_bars(
    report: ComparisonReport,
    attr: str,
    gain_attr: str | None,
    unit: str,
    title: str,
    path: Path,
    decimals: int = 1,
) -> Path:
    apply_style()
    names = list(report.metrics)
    values = [getattr(report.metrics[n], attr) for n in names]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    bars = ax.bar(
        [STRATEGY_LABELS.get(n, n) for n in names],
        values,
        width=0.55,
        color=[STRATEGY_COLORS.get(n, "#2a78d6") for n in names],
        edgecolor="white",
        linewidth=2,
    )
    for name, bar, value in zip(names, bars, values, strict=True):
        label = f"{fmt_br(value, decimals)} {unit}"
        gain = getattr(report.metrics[name], gain_attr) if gain_attr else None
        if gain is not None:
            label += f"\n{describe_change(gain)}"
        ax.annotate(
            label,
            (bar.get_x() + bar.get_width() / 2, bar.get_height()),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
            color=TEXT_PRIMARY,
        )
    ax.set_ylim(0, max(values, default=1) * 1.25 or 1)
    ax.set_ylabel(unit)
    clean_axes(ax)
    best = STRATEGY_LABELS.get(min(names, key=lambda n: getattr(report.metrics[n], attr)))
    _title(ax, title, f"Menor é melhor · melhor: {best} · variação em relação à rota manual")
    return save(fig, path)


def plot_route_load(report: ComparisonReport, courier_order: list[str], path: Path) -> Path:
    """Carga por entregador: pedidos (esquerda) e minutos de rota (direita), por estratégia."""
    apply_style()
    names = list(report.route_metrics)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    x = np.arange(len(courier_order))
    width = 0.8 / max(len(names), 1)
    for ax, field, unit, title in (
        (axes[0], "orders_count", "pedidos", "Pedidos por entregador"),
        (axes[1], "minutes", "min", "Duração da rota por entregador"),
    ):
        for i, name in enumerate(names):
            by_courier = {rm.courier_id: getattr(rm, field) for rm in report.route_metrics[name]}
            values = [by_courier.get(c, 0) for c in courier_order]
            bars = ax.bar(
                x + (i - (len(names) - 1) / 2) * width,
                values,
                width=width,
                color=STRATEGY_COLORS.get(name),
                edgecolor="white",
                linewidth=1.5,
                label=STRATEGY_LABELS.get(name, name),
            )
            for bar, value in zip(bars, values, strict=True):
                if value:
                    ax.annotate(
                        f"{value:.0f}",
                        (bar.get_x() + bar.get_width() / 2, value),
                        xytext=(0, 2),
                        textcoords="offset points",
                        ha="center",
                        fontsize=6.5,
                        color=TEXT_SECONDARY,
                    )
        ax.set_xticks(x, courier_order)
        ax.set_ylabel(unit)
        clean_axes(ax)
        ax.set_title(title, loc="left")
    axes[0].legend(loc="upper left", bbox_to_anchor=(0, -0.1), ncol=len(names))
    fig.suptitle(
        "Carga de trabalho por entregador",
        x=0.01,
        ha="left",
        fontsize=13,
        fontweight="bold",
        color=TEXT_PRIMARY,
    )
    fig.tight_layout()
    return save(fig, path)


def plot_k_evaluation(
    evaluation: list[dict[str, float]], chosen_k: int, out_dir: Path
) -> dict[str, Path]:
    """Cotovelo (inércia) e silhueta para k = 2..8, marcando o k usado."""
    apply_style()
    ks = [e["k"] for e in evaluation]
    paths = {}

    fig, ax = plt.subplots(figsize=(7, 4.2))
    inertia = [e["inertia"] for e in evaluation]
    ax.plot(ks, inertia, color=STRATEGY_COLORS["kmeans_astar"], lw=2, marker="o", markersize=7)
    for k, value in zip(ks, inertia, strict=True):
        ax.annotate(
            fmt_br(value),
            (k, value),
            xytext=(0, 7),
            textcoords="offset points",
            ha="center",
            fontsize=7,
            color=TEXT_SECONDARY,
        )
    if chosen_k in ks:
        ax.axvline(chosen_k, color=TEXT_SECONDARY, lw=1, ls="--")
        ax.annotate(
            f"k usado = {chosen_k}\n(nº de entregadores)",
            (chosen_k, max(inertia)),
            xytext=(6, -4),
            textcoords="offset points",
            fontsize=8,
            va="top",
            color=TEXT_PRIMARY,
        )
    ax.set_xlabel("k (número de zonas)")
    ax.set_ylabel("Inércia (km²)")
    ax.set_xticks(ks)
    clean_axes(ax, "both")
    _title(
        ax,
        "Método do cotovelo — K-Means",
        "Inércia = soma das distâncias² de cada pedido ao centróide da zona",
    )
    paths["kmeans_elbow"] = save(fig, out_dir / "kmeans_elbow.png")

    fig, ax = plt.subplots(figsize=(7, 4.2))
    silhouette = [e["silhouette"] for e in evaluation]
    best_k = ks[int(np.argmax(silhouette))] if ks else None
    colors = [STRATEGY_COLORS["kmeans_astar"] if k == chosen_k else "#86b6ef" for k in ks]
    bars = ax.bar(ks, silhouette, width=0.6, color=colors, edgecolor="white", linewidth=2)
    for k, bar, value in zip(ks, bars, silhouette, strict=True):
        tag = " (melhor)" if k == best_k else ""
        ax.annotate(
            f"{fmt_br(value, 2)}{tag}",
            (bar.get_x() + bar.get_width() / 2, value),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            fontsize=7,
            color=TEXT_PRIMARY,
        )
    ax.set_xlabel("k (número de zonas)")
    ax.set_ylabel("Silhueta média")
    ax.set_xticks(ks)
    ax.set_ylim(0, max(silhouette, default=1) * 1.2)
    clean_axes(ax)
    _title(
        ax,
        "Silhueta — K-Means",
        f"Maior é melhor · barra escura = k usado ({chosen_k}) · melhor silhueta: k = {best_k}",
    )
    paths["kmeans_silhouette"] = save(fig, out_dir / "kmeans_silhouette.png")
    return paths


def generate_charts(
    report: ComparisonReport,
    courier_order: list[str],
    evaluation: list[dict[str, float]],
    chosen_k: int,
    out_dir: Path,
) -> dict[str, Path]:
    """Gera todos os gráficos em ``out_dir/charts`` e devolve ``{nome: caminho}``."""
    charts = Path(out_dir) / "charts"
    has_gain = BASELINE in report.metrics
    paths = {
        "distance_comparison": _strategy_bars(
            report,
            "total_km",
            "gain_vs_manual_km" if has_gain else None,
            "km",
            "Distância total percorrida",
            charts / "distance_comparison.png",
        ),
        "time_comparison": _strategy_bars(
            report,
            "total_min",
            "gain_vs_manual_min" if has_gain else None,
            "min",
            "Tempo total de rota",
            charts / "time_comparison.png",
        ),
        "cost_comparison": _strategy_bars(
            report,
            "total_cost",
            "gain_vs_manual_cost" if has_gain else None,
            "R$",
            "Custo total de deslocamento (km × custo/km)",
            charts / "cost_comparison.png",
            2,
        ),
        "route_load": plot_route_load(report, courier_order, charts / "route_load.png"),
        "execution_time": _strategy_bars(
            report,
            "compute_ms",
            None,
            "ms",
            "Tempo de cálculo de cada estratégia",
            charts / "execution_time.png",
        ),
    }
    paths.update(plot_k_evaluation(evaluation, chosen_k, charts))
    return paths
