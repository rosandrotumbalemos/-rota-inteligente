"""Mapas do grafo, das zonas e das rotas (matplotlib + networkx; sem Google Maps nem APIs).

Os mapas usam as coordenadas reais (longitude no eixo x, latitude no eixo y) com proporção
geográfica correta. Arquivos gerados em ``<outputs>/maps``:

- ``graph_map.png``: nós, ruas, depósito e pedidos (com a ligação de cada pedido ao nó do snap).
- ``zones_map.png``: zonas do K-Means após o balanceamento, com centróides e contorno.
- ``routes_<estratégia>.png``: rotas de cada entregador, numeradas na ordem de visita.
- ``comparison_map.png``: as três estratégias lado a lado, na mesma escala.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from scipy.spatial import ConvexHull, QhullError

from rota_core.algorithms.kmeans_astar import KMeansAStarPlan
from rota_core.domain.models import Order, Route
from rota_core.graph.city_graph import depot_id
from rota_core.reporting.style import (
    COURIER_COLORS,
    DEPOT_COLOR,
    EDGE_COLOR,
    NODE_COLOR,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    ZONE_COLORS,
    apply_style,
    color_for,
    geo_aspect,
    save,
)
from rota_core.services.metrics import STRATEGY_LABELS, fmt_br

ROUTE_OFFSET_DEG = 0.00012  # desloca levemente cada entregador para as linhas não se taparem


def _positions(graph: nx.DiGraph) -> dict[str, tuple[float, float]]:
    return {n: (d["lon"], d["lat"]) for n, d in graph.nodes(data=True)}


def _mean_lat(graph: nx.DiGraph) -> float:
    return float(np.mean([d["lat"] for _, d in graph.nodes(data=True)]))


def _draw_base(ax: Axes, graph: nx.DiGraph, labels: bool = False, faded: bool = True) -> None:
    """Ruas, nós e depósito. ``faded`` deixa o fundo discreto para as rotas se destacarem."""
    pos = _positions(graph)
    undirected = graph.to_undirected(as_view=True)
    nx.draw_networkx_edges(
        undirected,
        pos,
        ax=ax,
        edge_color=EDGE_COLOR,
        width=0.9 if faded else 1.4,
        alpha=0.8 if faded else 1.0,
    )
    depot = depot_id(graph)
    others = [n for n in graph.nodes if n != depot]
    nx.draw_networkx_nodes(
        graph,
        pos,
        nodelist=others,
        ax=ax,
        node_size=14 if faded else 60,
        node_color=NODE_COLOR,
        linewidths=0,
    )
    if labels:
        nx.draw_networkx_labels(
            graph,
            {n: (x, y + 0.0011) for n, (x, y) in pos.items()},
            ax=ax,
            labels={n: n for n in others},
            font_size=6,
            font_color=TEXT_SECONDARY,
        )
    x, y = pos[depot]
    ax.scatter(
        [x], [y], marker="*", s=420, color=DEPOT_COLOR, edgecolors="white", linewidths=1.2, zorder=6
    )
    ax.annotate(
        "Depósito",
        (x, y),
        xytext=(8, -12),
        textcoords="offset points",
        fontsize=8,
        fontweight="bold",
        color=TEXT_PRIMARY,
        zorder=7,
    )


def _finish(ax: Axes, graph: nx.DiGraph, title: str, subtitle: str | None = None) -> None:
    ax.set_title(title, loc="left", pad=18 if subtitle else 8)
    if subtitle:
        ax.text(0, 1.015, subtitle, transform=ax.transAxes, fontsize=8, color=TEXT_SECONDARY)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.tick_params(left=True, bottom=True, labelleft=True, labelbottom=True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    geo_aspect(ax, _mean_lat(graph))


def _depot_handle() -> Line2D:
    return Line2D(
        [],
        [],
        marker="*",
        color="none",
        markerfacecolor=DEPOT_COLOR,
        markersize=12,
        label="Depósito (cozinha)",
    )


def plot_graph_map(graph: nx.DiGraph, orders: list[Order], path: Path) -> Path:
    """Diagrama do grafo: 40 nós, ruas, depósito e pedidos ligados ao nó do snap."""
    apply_style()
    fig, ax = plt.subplots(figsize=(9, 8))
    _draw_base(ax, graph, labels=True, faded=False)
    for o in orders:
        if o.node_id:
            nx_, ny_ = graph.nodes[o.node_id]["lon"], graph.nodes[o.node_id]["lat"]
            ax.plot([o.lon, nx_], [o.lat, ny_], color=COURIER_COLORS[0], lw=0.7, alpha=0.6)
    ax.scatter(
        [o.lon for o in orders],
        [o.lat for o in orders],
        s=28,
        color=COURIER_COLORS[0],
        edgecolors="white",
        linewidths=0.8,
        zorder=5,
    )
    handles = [
        _depot_handle(),
        Line2D(
            [],
            [],
            marker="o",
            color="none",
            markerfacecolor=NODE_COLOR,
            markersize=6,
            label=f"Nó / bairro ({graph.number_of_nodes() - 1})",
        ),
        Line2D(
            [],
            [],
            color=EDGE_COLOR,
            lw=1.4,
            label=f"Rua de mão dupla ({graph.number_of_edges() // 2})",
        ),
        Line2D(
            [],
            [],
            marker="o",
            color=COURIER_COLORS[0],
            markersize=6,
            lw=0.7,
            label=f"Pedido ({len(orders)}) e ligação ao nó mais próximo",
        ),
    ]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 1))
    _finish(
        ax,
        graph,
        "Grafo da cidade — Sabor Express (centro de São Paulo)",
        "Nós = bairros/pontos; arestas = ruas com peso em km e minutos",
    )
    return save(fig, path)


def plot_zones_map(graph: nx.DiGraph, plan: KMeansAStarPlan, path: Path) -> Path:
    """Zonas do K-Means (após balanceamento): pedidos por zona, contorno e centróide."""
    apply_style()
    fig, ax = plt.subplots(figsize=(9, 8))
    _draw_base(ax, graph)
    handles = [_depot_handle()]
    for zone in plan.zones:
        color = color_for(zone.cluster_id, ZONE_COLORS)
        xs = np.array([o.lon for o in zone.orders])
        ys = np.array([o.lat for o in zone.orders])
        if len(zone.orders) >= 3:
            try:
                hull = ConvexHull(np.column_stack([xs, ys]))
                ax.fill(xs[hull.vertices], ys[hull.vertices], color=color, alpha=0.12, lw=0)
                ax.plot(
                    *np.column_stack([xs[hull.vertices], ys[hull.vertices]])[
                        np.r_[range(len(hull.vertices)), 0]
                    ].T,
                    color=color,
                    lw=1,
                    alpha=0.6,
                )
            except QhullError:
                pass  # pontos colineares: sem contorno
        ax.scatter(xs, ys, s=46, color=color, edgecolors="white", linewidths=1, zorder=5)
        ax.scatter(
            [zone.centroid_lon],
            [zone.centroid_lat],
            marker="X",
            s=110,
            color=color,
            edgecolors=TEXT_PRIMARY,
            linewidths=0.8,
            zorder=6,
        )
        courier = plan.assignment.get(zone.cluster_id, "—")
        handles.append(
            Line2D(
                [],
                [],
                marker="o",
                color="none",
                markerfacecolor=color,
                markersize=8,
                label=f"Zona {zone.cluster_id} → {courier} ({zone.size} pedidos, "
                f"{fmt_br(plan.zone_km[zone.cluster_id])} km)",
            )
        )
    handles.append(
        Line2D(
            [],
            [],
            marker="X",
            color="none",
            markerfacecolor="white",
            markeredgecolor=TEXT_PRIMARY,
            markersize=8,
            label="Centróide da zona",
        )
    )
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 1))
    _finish(
        ax,
        graph,
        f"Zonas de entrega — K-Means (k = {len(plan.zones)}) após balanceamento",
        "Cor = zona; X = centróide; a zona é atribuída ao entregador pelo algoritmo húngaro",
    )
    return save(fig, path)


def _draw_routes(
    ax: Axes, graph: nx.DiGraph, routes: list[Route], courier_order: list[str]
) -> list[Line2D]:
    pos = _positions(graph)
    handles = []
    for route in routes:
        index = courier_order.index(route.courier_id)
        color = color_for(index, COURIER_COLORS)
        shift = (index - (len(courier_order) - 1) / 2) * ROUTE_OFFSET_DEG
        xs = [pos[n][0] + shift for n in route.path]
        ys = [pos[n][1] + shift for n in route.path]
        ax.plot(xs, ys, color=color, lw=2, alpha=0.9, solid_capstyle="round", zorder=3)
        for stop in route.stops:
            x, y = pos[stop.node_id]
            ax.scatter(
                [x + shift],
                [y + shift],
                s=70,
                color=color,
                edgecolors="white",
                linewidths=1.2,
                zorder=5,
            )
            ax.annotate(
                str(stop.seq),
                (x + shift, y + shift),
                ha="center",
                va="center",
                fontsize=5.5,
                color="white",
                fontweight="bold",
                zorder=6,
            )
        zone = "" if route.cluster_label is None else f", zona {route.cluster_label}"
        handles.append(
            Line2D(
                [],
                [],
                color=color,
                lw=2.5,
                label=(
                    f"{route.courier_id}{zone}: {len(route.stops)} pedidos, "
                    f"{fmt_br(route.total_km)} km, {route.total_min:.0f} min"
                ),
            )
        )
    return handles


def plot_routes_map(
    graph: nx.DiGraph, routes: list[Route], strategy: str, courier_order: list[str], path: Path
) -> Path:
    """Rotas de uma estratégia. Números = ordem de visita das paradas de cada entregador."""
    apply_style()
    fig, ax = plt.subplots(figsize=(9, 8))
    _draw_base(ax, graph)
    handles = [_depot_handle(), *_draw_routes(ax, graph, routes, courier_order)]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 1))
    km = sum(r.total_km for r in routes)
    minutes = sum(r.total_min for r in routes)
    _finish(
        ax,
        graph,
        f"Rotas — {STRATEGY_LABELS.get(strategy, strategy)}",
        f"Total: {fmt_br(km)} km · {minutes:.0f} min · números = ordem de visita",
    )
    return save(fig, path)


def plot_comparison_map(
    graph: nx.DiGraph, results: dict[str, list[Route]], courier_order: list[str], path: Path
) -> Path:
    """As estratégias lado a lado, mesma escala, para comparação visual."""
    apply_style()
    fig, axes = plt.subplots(
        1, len(results), figsize=(6 * len(results), 6.4), sharex=True, sharey=True
    )
    axes = np.atleast_1d(axes)
    for ax, (name, routes) in zip(axes, results.items(), strict=True):
        _draw_base(ax, graph)
        _draw_routes(ax, graph, routes, courier_order)
        km = sum(r.total_km for r in routes)
        minutes = sum(r.total_min for r in routes)
        longest = max((r.total_min for r in routes), default=0)
        _finish(
            ax,
            graph,
            STRATEGY_LABELS.get(name, name),
            f"{fmt_br(km)} km · {minutes:.0f} min · maior rota {longest:.0f} min",
        )
    legend = [
        Line2D([], [], color=color_for(i, COURIER_COLORS), lw=2.5, label=c)
        for i, c in enumerate(courier_order)
    ]
    fig.legend(
        handles=[_depot_handle(), *legend],
        loc="lower center",
        ncol=len(legend) + 1,
        bbox_to_anchor=(0.5, -0.02),
    )
    fig.suptitle(
        "Comparação das rotas — mesmo grafo, mesmos pedidos",
        x=0.01,
        ha="left",
        fontsize=13,
        fontweight="bold",
        color=TEXT_PRIMARY,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.97))
    return save(fig, path)


def generate_maps(
    graph: nx.DiGraph,
    orders: list[Order],
    results: dict[str, list[Route]],
    plan: KMeansAStarPlan | None,
    courier_order: list[str],
    out_dir: Path,
) -> dict[str, Path]:
    """Gera todos os mapas em ``out_dir/maps`` e devolve ``{nome: caminho}``."""
    maps_dir = Path(out_dir) / "maps"
    paths = {"graph_map": plot_graph_map(graph, orders, maps_dir / "graph_map.png")}
    if plan is not None:
        paths["zones_map"] = plot_zones_map(graph, plan, maps_dir / "zones_map.png")
    for name, routes in results.items():
        paths[f"routes_{name}"] = plot_routes_map(
            graph, routes, name, courier_order, maps_dir / f"routes_{name}.png"
        )
    paths["comparison_map"] = plot_comparison_map(
        graph, results, courier_order, maps_dir / "comparison_map.png"
    )
    return paths
