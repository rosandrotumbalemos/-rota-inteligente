"""Gerador determinístico de dados fictícios da Sabor Express (região central de São Paulo).

Nenhum dado pessoal real: nomes de clientes e entregadores são rótulos genéricos e as
coordenadas são pontos sorteados dentro de um retângulo do centro da cidade.
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

from rota_core.data.loaders import (
    COURIERS_FILE,
    EDGES_FILE,
    NODES_FILE,
    ORDERS_FILE,
    REQUIRED_COLUMNS,
)
from rota_core.graph.city_graph import haversine_km

# Retângulo aproximado do centro expandido de São Paulo (Sé, República, Bela Vista, Liberdade...)
LAT_MIN, LAT_MAX = -23.575, -23.525
LON_MIN, LON_MAX = -46.665, -46.605
DEPOT = {"id": "N00", "name": "Sabor Express - Cozinha Central", "lat": -23.5505, "lon": -46.6333}

N_NODES = 40
N_EDGES = 60
N_ORDERS = 20
N_COURIERS = 4
MIN_NODE_SPACING_KM = 0.35
DETOUR_RANGE = (1.15, 1.40)  # rua é mais longa que a linha reta
SPEEDS_KMH = (20, 30, 40)
SPEED_WEIGHTS = (0.4, 0.4, 0.2)
PEAK_START = datetime(2026, 11, 12, 11, 30)  # pico do almoço


def _sample_nodes(rng: random.Random) -> list[dict]:
    nodes = [{**DEPOT, "kind": "depot"}]
    attempts = 0
    while len(nodes) < N_NODES:
        attempts += 1
        if attempts > 50_000:
            raise RuntimeError("não foi possível posicionar os nós com o espaçamento mínimo")
        lat = round(rng.uniform(LAT_MIN, LAT_MAX), 6)
        lon = round(rng.uniform(LON_MIN, LON_MAX), 6)
        if all(haversine_km(lat, lon, n["lat"], n["lon"]) >= MIN_NODE_SPACING_KM for n in nodes):
            idx = len(nodes)
            nodes.append(
                {
                    "id": f"N{idx:02d}",
                    "name": f"Ponto {idx:02d}",
                    "kind": "bairro",
                    "lat": lat,
                    "lon": lon,
                }
            )
    return nodes


def _sample_edges(rng: random.Random, nodes: list[dict]) -> list[dict]:
    """Árvore geradora mínima (Prim) garante conectividade; depois adiciona as ligações curtas
    restantes até ``N_EDGES``."""
    n = len(nodes)
    dist = [[haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) for b in nodes] for a in nodes]

    in_tree = {0}
    pairs: list[tuple[int, int]] = []
    while len(in_tree) < n:
        i, j = min(
            ((i, j) for i in in_tree for j in range(n) if j not in in_tree),
            key=lambda p: dist[p[0]][p[1]],
        )
        pairs.append((i, j))
        in_tree.add(j)

    existing = {frozenset(p) for p in pairs}
    candidates = sorted(
        ((i, j) for i in range(n) for j in range(i + 1, n) if frozenset((i, j)) not in existing),
        key=lambda p: dist[p[0]][p[1]],
    )
    pairs.extend(candidates[: N_EDGES - len(pairs)])

    edges = []
    for i, j in pairs:
        edges.append(
            {
                "source": nodes[i]["id"],
                "target": nodes[j]["id"],
                "distance_km": round(dist[i][j] * rng.uniform(*DETOUR_RANGE), 3),
                "speed_kmh": rng.choices(SPEEDS_KMH, weights=SPEED_WEIGHTS)[0],
                "oneway": False,
            }
        )
    return edges


def _sample_orders(rng: random.Random, nodes: list[dict]) -> list[dict]:
    targets = [n for n in nodes if n["kind"] != "depot"]
    minutes = sorted(rng.randint(0, 60) for _ in range(N_ORDERS))
    orders = []
    for idx, minute in enumerate(minutes, start=1):
        near = rng.choice(targets)
        orders.append(
            {
                "id": f"P{idx:03d}",
                "code": f"SE-{idx:04d}",
                "customer_alias": f"Cliente {idx:03d}",
                "address_label": f"Próximo ao {near['name']}",
                "lat": round(near["lat"] + rng.uniform(-0.0012, 0.0012), 6),
                "lon": round(near["lon"] + rng.uniform(-0.0012, 0.0012), 6),
                "created_at": (PEAK_START + timedelta(minutes=minute)).isoformat(),
                "value": round(rng.uniform(25, 120), 2),
            }
        )
    return orders


def _sample_couriers(rng: random.Random) -> list[dict]:
    couriers = []
    for idx in range(1, N_COURIERS + 1):
        vehicle = "bike" if idx == N_COURIERS else "moto"
        cost = 0.10 if vehicle == "bike" else round(rng.uniform(0.40, 0.55), 2)
        couriers.append(
            {
                "id": f"E{idx:02d}",
                "name": f"Entregador {idx:02d}",
                "vehicle": vehicle,
                "cost_per_km": cost,
            }
        )
    return couriers


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate_dataset(output_dir: Path, seed: int = 42) -> dict[str, Path]:
    """Gera os quatro CSVs em ``output_dir``. Mesma seed => arquivos idênticos byte a byte."""
    rng = random.Random(seed)
    nodes = _sample_nodes(rng)
    edges = _sample_edges(rng, nodes)
    orders = _sample_orders(rng, nodes)
    couriers = _sample_couriers(rng)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        NODES_FILE: nodes,
        EDGES_FILE: edges,
        ORDERS_FILE: orders,
        COURIERS_FILE: couriers,
    }
    paths = {}
    for name, rows in files.items():
        path = output_dir / name
        _write_csv(path, REQUIRED_COLUMNS[name], rows)
        paths[name] = path
    return paths
