"""Estilo visual comum dos mapas e gráficos (matplotlib, sem serviços externos).

Paleta categórica validada para daltonismo (verificação automática de separação CVD):

- Entregadores: azul, laranja, verde-água, amarelo (slots 1–4), na ordem dos ids.
- Zonas: magenta, verde, violeta, vermelho (slots 5–8): cores diferentes das dos entregadores.
- Estratégias: manual em cinza (referência), vizinho mais próximo em laranja, K-Means + A*
  em azul. Nos gráficos a estratégia também vem escrita no eixo, então a cor nunca é a única
  identificação.
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # renderização em arquivo, sem janela

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

DPI = 200

SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#1f1f1e"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
EDGE_COLOR = "#c9c8c2"
NODE_COLOR = "#8a8985"
DEPOT_COLOR = "#1f1f1e"

COURIER_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#6250d6", "#e34948"]
ZONE_COLORS = ["#e87ba4", "#008300", "#6250d6", "#e34948", "#2a78d6", "#eb6834"]
STRATEGY_COLORS = {
    "manual": "#8a8985",
    "nearest_neighbor": "#eb6834",
    "kmeans_astar": "#2a78d6",
}


def color_for(index: int, palette: list[str]) -> str:
    """Cor fixa por posição. Mais itens que cores repete a paleta (só ocorre com > 6 itens)."""
    return palette[index % len(palette)]


def apply_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": TEXT_SECONDARY,
            "axes.titlecolor": TEXT_PRIMARY,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.labelsize": 9,
            "xtick.color": TEXT_SECONDARY,
            "ytick.color": TEXT_SECONDARY,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
            "legend.frameon": False,
            "font.family": "DejaVu Sans",
        }
    )


def clean_axes(ax: Axes, grid_axis: str = "y") -> None:
    """Grade discreta e só os eixos necessários."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def geo_aspect(ax: Axes, mean_lat: float) -> None:
    """Proporção correta do mapa: 1° de longitude é menor que 1° de latitude fora do equador."""
    ax.set_aspect(1 / math.cos(math.radians(mean_lat)))


def save(fig: Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return path
