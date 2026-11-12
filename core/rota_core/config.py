"""Configurações do núcleo, lidas de variáveis de ambiente (prefixo ``ROTA_``) ou do ``.env``."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# core/rota_core/config.py -> parents[2] = raiz do repositório
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Parâmetros globais do núcleo de IA."""

    model_config = SettingsConfigDict(
        env_prefix="ROTA_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(default=REPO_ROOT / "data", description="Pasta dos CSVs de entrada.")
    outputs_dir: Path = Field(
        default=REPO_ROOT / "outputs", description="Pasta de mapas, gráficos e relatórios."
    )
    seed: int = Field(default=42, description="Semente para geração de dados e K-Means.")
    n_clusters: int = Field(default=4, ge=1, description="Número padrão de zonas (K do K-Means).")

    @field_validator("data_dir", "outputs_dir")
    @classmethod
    def _resolve_relative(cls, value: Path) -> Path:
        """Caminhos relativos são resolvidos a partir da raiz do repositório."""
        return value if value.is_absolute() else (REPO_ROOT / value).resolve()


def get_settings() -> Settings:
    """Retorna uma instância nova de ``Settings`` (sem cache, para facilitar testes)."""
    return Settings()
