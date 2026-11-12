"""Agrupamento de pedidos em zonas com K-Means e balanceamento simples de carga.

Projeção: antes do K-Means, latitude/longitude viram coordenadas planas em km
(projeção equiretangular centrada nos pedidos). Em graus, 1° de longitude em São Paulo mede
~0,92 de 1° de latitude; agrupar em graus "achataria" o mapa. Com km nos dois eixos, a
distância euclidiana usada pelo K-Means corresponde à distância real em linha reta.

Limitação central: o K-Means agrupa por proximidade geográfica em linha reta e não conhece a
malha viária. Dois pedidos vizinhos no mapa podem estar longe pelas ruas (mão única, ausência de
ligação direta), e o K-Means os colocará na mesma zona mesmo assim. O A* corrige o trajeto
dentro da zona, mas não a composição da zona.
"""

from __future__ import annotations

import math

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from rota_core.domain.models import Order, Zone

KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON_EQUATOR = 111.320


class ClusteringError(ValueError):
    """Entrada inválida para o agrupamento."""


def project_km(lat: float, lon: float, ref_lat: float) -> tuple[float, float]:
    """Coordenadas planas (x, y) em km, projeção equiretangular na latitude de referência."""
    x = lon * KM_PER_DEG_LON_EQUATOR * math.cos(math.radians(ref_lat))
    y = lat * KM_PER_DEG_LAT
    return x, y


def _project_orders(orders: list[Order]) -> tuple[np.ndarray, float]:
    ref_lat = float(np.mean([o.lat for o in orders]))
    points = np.array([project_km(o.lat, o.lon, ref_lat) for o in orders])
    return points, ref_lat


def _centroid(orders: list[Order]) -> tuple[float, float]:
    return (
        float(np.mean([o.lat for o in orders])),
        float(np.mean([o.lon for o in orders])),
    )


def cluster_orders(orders: list[Order], k: int, seed: int = 42) -> list[Zone]:
    """Agrupa os pedidos em até ``k`` zonas com K-Means (``n_init=10``, ``random_state=seed``).

    ``k`` efetivo = ``min(k, nº de pedidos, nº de coordenadas distintas)``, para nunca pedir
    mais grupos do que pontos distintos. Zonas são numeradas 0..k-1 por longitude do centróide
    (oeste -> leste), para a numeração ser estável e legível nos mapas.
    """
    if not orders:
        raise ClusteringError("não há pedidos para agrupar")
    if k < 1:
        raise ClusteringError(f"k deve ser >= 1, recebido {k}")

    distinct = len({(o.lat, o.lon) for o in orders})
    k_eff = min(k, len(orders), distinct)
    points, _ = _project_orders(orders)
    model = KMeans(n_clusters=k_eff, n_init=10, random_state=seed)
    labels = model.fit_predict(points)

    groups: dict[int, list[Order]] = {}
    for order, label in zip(orders, labels, strict=True):
        groups.setdefault(int(label), []).append(order)

    ordered = sorted(groups.values(), key=lambda g: (_centroid(g)[1], _centroid(g)[0]))
    return [
        Zone(cluster_id=i, centroid_lat=lat, centroid_lon=lon, orders=group)
        for i, group in enumerate(ordered)
        for lat, lon in [_centroid(group)]
    ]


def evaluate_k(
    orders: list[Order], ks: range | list[int] = range(2, 9), seed: int = 42
) -> list[dict[str, float]]:
    """Inércia (cotovelo) e silhueta do K-Means para cada ``k`` (coordenadas em km).

    - Inércia: soma dos quadrados das distâncias de cada pedido ao centróide (km²). Cai sempre
      com k maior; o "cotovelo" indica onde o ganho passa a ser pequeno.
    - Silhueta: de -1 a 1; quanto maior, mais separados e coesos os grupos.

    Valores de k impossíveis (k < 2 ou k >= nº de pontos distintos) são ignorados.
    """
    points, _ = _project_orders(orders)
    distinct = len({(o.lat, o.lon) for o in orders})
    results = []
    for k in ks:
        if k < 2 or k >= distinct:
            continue
        model = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(points)
        results.append(
            {
                "k": k,
                "inertia": float(model.inertia_),
                "silhouette": float(silhouette_score(points, model.labels_)),
            }
        )
    return results


def zone_capacity(n_orders: int, n_zones: int, max_extra: int = 2) -> int:
    """Máximo de pedidos por zona: média arredondada para cima + folga ``max_extra``."""
    return math.ceil(n_orders / n_zones) + max_extra


def balance_zones(zones: list[Zone], max_extra: int = 2) -> list[Zone]:
    """Limita o tamanho das zonas a ``zone_capacity`` movendo pedidos para zonas vizinhas.

    Enquanto houver zona acima do limite, escolhe na maior zona o movimento de menor
    "custo geográfico": o pedido e a zona de destino (com vaga) que minimizam
    ``dist(pedido, centróide destino) - dist(pedido, centróide origem)``. Assim saem primeiro
    os pedidos de borda, que já estão quase tão perto da zona vizinha.

    Garantias: nenhuma zona fica vazia (só zonas acima do limite cedem pedidos, e o limite é
    >= 1), cada pedido continua em exatamente uma zona e o resultado é determinístico.
    Os centróides são recalculados no fim.
    """
    if not zones:
        return []
    n_orders = sum(z.size for z in zones)
    cap = zone_capacity(n_orders, len(zones), max_extra)
    _, ref_lat = _project_orders([o for z in zones for o in z.orders])

    members = {z.cluster_id: list(z.orders) for z in zones}
    centers = {z.cluster_id: project_km(z.centroid_lat, z.centroid_lon, ref_lat) for z in zones}

    def dist(order: Order, cid: int) -> float:
        x, y = project_km(order.lat, order.lon, ref_lat)
        cx, cy = centers[cid]
        return math.hypot(x - cx, y - cy)

    while True:
        source = max(members, key=lambda cid: (len(members[cid]), -cid))
        if len(members[source]) <= cap:
            break
        targets = [cid for cid in members if cid != source and len(members[cid]) < cap]
        penalty, _, order, target = min(
            (dist(o, t) - dist(o, source), o.id, o, t) for o in members[source] for t in targets
        )
        members[source].remove(order)
        members[target].append(order)

    result = []
    for z in zones:
        group = members[z.cluster_id]
        lat, lon = _centroid(group)
        result.append(
            Zone(cluster_id=z.cluster_id, centroid_lat=lat, centroid_lon=lon, orders=group)
        )
    return result
