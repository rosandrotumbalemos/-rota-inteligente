"""Leitura, validação de colunas e geração determinística dos CSVs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from rota_core.data import DataValidationError, generate_dataset, load_dataset, validate_dataset
from rota_core.data.loaders import (
    EDGES_FILE,
    NODES_FILE,
    REQUIRED_COLUMNS,
    load_nodes,
    validate_columns,
)
from rota_core.domain import Courier, Edge, Node, NodeKind, Order

CSV_FILES = ("nodes.csv", "edges.csv", "orders.csv", "couriers.csv")


def test_le_csvs_versionados(repo_data_dir: Path) -> None:
    dataset = load_dataset(repo_data_dir)
    assert all(isinstance(n, Node) for n in dataset.nodes)
    assert all(isinstance(e, Edge) for e in dataset.edges)
    assert all(isinstance(o, Order) for o in dataset.orders)
    assert all(isinstance(c, Courier) for c in dataset.couriers)
    assert validate_dataset(dataset) == []


def test_csvs_versionados_iguais_ao_gerador(repo_data_dir: Path, generated_dir: Path) -> None:
    for name in CSV_FILES:
        assert (repo_data_dir / name).read_bytes() == (generated_dir / name).read_bytes(), name


@pytest.mark.parametrize("file_name", list(REQUIRED_COLUMNS))
def test_colunas_obrigatorias_presentes(generated_dir: Path, file_name: str) -> None:
    df = pd.read_csv(generated_dir / file_name)
    validate_columns(df, REQUIRED_COLUMNS[file_name], file_name)


def test_coluna_ausente_gera_erro(generated_dir: Path) -> None:
    path = generated_dir / NODES_FILE
    pd.read_csv(path).drop(columns=["lat"]).to_csv(path, index=False)
    with pytest.raises(DataValidationError, match="lat"):
        load_nodes(path)


def test_arquivo_ausente_gera_erro(tmp_path: Path) -> None:
    with pytest.raises(DataValidationError, match="não encontrado"):
        load_dataset(tmp_path)


def test_valor_invalido_indica_linha(generated_dir: Path) -> None:
    path = generated_dir / EDGES_FILE
    df = pd.read_csv(path)
    df.loc[0, "distance_km"] = -1
    df.to_csv(path, index=False)
    with pytest.raises(DataValidationError, match="linha 2"):
        load_dataset(generated_dir)


def test_geracao_deterministica(tmp_path: Path) -> None:
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    generate_dataset(a, seed=7)
    generate_dataset(b, seed=7)
    generate_dataset(c, seed=8)
    for name in CSV_FILES:
        assert (a / name).read_bytes() == (b / name).read_bytes()
    assert any((a / name).read_bytes() != (c / name).read_bytes() for name in CSV_FILES)


def test_existe_um_unico_deposito(dataset) -> None:
    depots = [n for n in dataset.nodes if n.kind == NodeKind.DEPOT]
    assert len(depots) == 1
    assert depots[0].id == "N00"


def test_quantidades(dataset) -> None:
    assert len(dataset.nodes) == 40
    assert len([n for n in dataset.nodes if n.kind == NodeKind.BAIRRO]) == 39
    assert len(dataset.edges) == 60
    assert len(dataset.orders) == 20
    assert len(dataset.couriers) == 4


def test_coordenadas_no_centro_de_sao_paulo(dataset) -> None:
    for item in [*dataset.nodes, *dataset.orders]:
        assert -23.58 <= item.lat <= -23.52
        assert -46.67 <= item.lon <= -46.60


def test_validacao_detecta_dois_depositos(dataset) -> None:
    extra = dataset.nodes[1].model_copy(update={"kind": NodeKind.DEPOT})
    broken = type(dataset)(
        nodes=[dataset.nodes[0], extra, *dataset.nodes[2:]],
        edges=dataset.edges,
        orders=dataset.orders,
        couriers=dataset.couriers,
    )
    assert any("depósito" in p for p in validate_dataset(broken))
