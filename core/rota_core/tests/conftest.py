"""Fixtures compartilhadas pelos testes."""

from __future__ import annotations

from pathlib import Path

import pytest

from rota_core.config import REPO_ROOT
from rota_core.data import Dataset, generate_dataset, load_dataset


@pytest.fixture(scope="session")
def repo_data_dir() -> Path:
    """Pasta data/ versionada no repositório."""
    return REPO_ROOT / "data"


@pytest.fixture()
def generated_dir(tmp_path: Path) -> Path:
    """Dados gerados do zero numa pasta temporária (seed padrão)."""
    generate_dataset(tmp_path, seed=42)
    return tmp_path


@pytest.fixture()
def dataset(generated_dir: Path) -> Dataset:
    return load_dataset(generated_dir)
