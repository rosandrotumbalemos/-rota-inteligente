"""Camada de dados: leitura, validação e geração dos CSVs."""

from rota_core.data.generator import generate_dataset
from rota_core.data.loaders import (
    Dataset,
    DataValidationError,
    load_couriers,
    load_dataset,
    load_edges,
    load_nodes,
    load_orders,
    validate_dataset,
)

__all__ = [
    "DataValidationError",
    "Dataset",
    "generate_dataset",
    "load_couriers",
    "load_dataset",
    "load_edges",
    "load_nodes",
    "load_orders",
    "validate_dataset",
]
