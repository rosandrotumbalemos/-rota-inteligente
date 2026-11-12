"""Leitura e validação dos CSVs de entrada, convertendo cada linha em modelo de domínio."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import pandas as pd
from pydantic import ValidationError

from rota_core.domain.models import Courier, Edge, Node, NodeKind, Order

NODES_FILE = "nodes.csv"
EDGES_FILE = "edges.csv"
ORDERS_FILE = "orders.csv"
COURIERS_FILE = "couriers.csv"

REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    NODES_FILE: ("id", "name", "kind", "lat", "lon"),
    EDGES_FILE: ("source", "target", "distance_km", "speed_kmh", "oneway"),
    ORDERS_FILE: (
        "id",
        "code",
        "customer_alias",
        "address_label",
        "lat",
        "lon",
        "created_at",
        "value",
    ),
    COURIERS_FILE: ("id", "name", "vehicle", "cost_per_km"),
}


class DataValidationError(ValueError):
    """Erro de dados de entrada (arquivo ausente, colunas faltando ou valores inválidos)."""


@dataclass(frozen=True)
class Dataset:
    nodes: list[Node]
    edges: list[Edge]
    orders: list[Order]
    couriers: list[Courier]


def _read_csv(path: Path, file_key: str) -> pd.DataFrame:
    if not path.exists():
        raise DataValidationError(f"arquivo não encontrado: {path}")
    df = pd.read_csv(path, dtype={"id": str, "source": str, "target": str, "code": str})
    validate_columns(df, REQUIRED_COLUMNS[file_key], path.name)
    return df


def validate_columns(df: pd.DataFrame, required: tuple[str, ...], name: str) -> None:
    """Levanta ``DataValidationError`` se faltar alguma coluna obrigatória."""
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise DataValidationError(f"{name}: colunas obrigatórias ausentes: {', '.join(missing)}")


def _to_models(df: pd.DataFrame, model: type, name: str) -> list:
    records = df.to_dict(orient="records")
    items = []
    for line, record in enumerate(records, start=2):  # linha 1 = cabeçalho
        try:
            items.append(model(**{k: v for k, v in record.items() if k in model.model_fields}))
        except ValidationError as exc:
            raise DataValidationError(f"{name}, linha {line}: {exc.errors()[0]['msg']}") from exc
    return items


def load_nodes(path: Path) -> list[Node]:
    return _to_models(_read_csv(path, NODES_FILE), Node, path.name)


def load_edges(path: Path) -> list[Edge]:
    df = _read_csv(path, EDGES_FILE)
    df["oneway"] = df["oneway"].astype(str).str.lower().isin({"true", "1", "sim"})
    return _to_models(df, Edge, path.name)


def load_orders(path: Path) -> list[Order]:
    return _to_models(_read_csv(path, ORDERS_FILE), Order, path.name)


def load_couriers(path: Path) -> list[Courier]:
    return _to_models(_read_csv(path, COURIERS_FILE), Courier, path.name)


def load_dataset(data_dir: Path) -> Dataset:
    """Carrega os quatro CSVs de ``data_dir``."""
    data_dir = Path(data_dir)
    return Dataset(
        nodes=load_nodes(data_dir / NODES_FILE),
        edges=load_edges(data_dir / EDGES_FILE),
        orders=load_orders(data_dir / ORDERS_FILE),
        couriers=load_couriers(data_dir / COURIERS_FILE),
    )


def validate_dataset(dataset: Dataset) -> list[str]:
    """Regras de consistência entre arquivos. Retorna a lista de problemas (vazia = válido)."""
    problems: list[str] = []
    node_ids = {n.id for n in dataset.nodes}

    for label, ids in (
        ("nós", [n.id for n in dataset.nodes]),
        ("pedidos", [o.id for o in dataset.orders]),
        ("entregadores", [c.id for c in dataset.couriers]),
    ):
        dup = [i for i, count in Counter(ids).items() if count > 1]
        if dup:
            problems.append(f"ids duplicados em {label}: {dup}")

    depots = [n for n in dataset.nodes if n.kind == NodeKind.DEPOT]
    if len(depots) != 1:
        problems.append(f"esperado exatamente 1 depósito, encontrado {len(depots)}")

    orphan = [(e.source, e.target) for e in dataset.edges if {e.source, e.target} - node_ids]
    if orphan:
        problems.append(f"arestas com nós inexistentes: {orphan}")

    pairs = Counter(frozenset((e.source, e.target)) for e in dataset.edges)
    if any(count > 1 for count in pairs.values()):
        problems.append("arestas duplicadas entre o mesmo par de nós")

    if dataset.nodes and not orphan:
        graph = nx.Graph()
        graph.add_nodes_from(node_ids)
        graph.add_edges_from((e.source, e.target) for e in dataset.edges)
        if not nx.is_connected(graph):
            problems.append("grafo desconexo: há bairros inalcançáveis a partir do depósito")

    if not dataset.orders:
        problems.append("nenhum pedido em orders.csv")
    if not any(c.active for c in dataset.couriers):
        problems.append("nenhum entregador ativo em couriers.csv")
    return problems
