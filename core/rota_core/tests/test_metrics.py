"""Modelo de métricas e cálculo da variação percentual em relação à rota manual."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rota_core.domain import Metrics
from rota_core.services.metrics import compute_metrics, gain_percent


def _metrics(**overrides) -> Metrics:
    base = dict(
        total_km=42.0,
        total_min=95.0,
        total_cost=18.5,
        avg_eta_min=22.0,
        max_route_min=31.0,
        balance_std=0.5,
        compute_ms=12.0,
    )
    return Metrics(**{**base, **overrides})


def test_metrics_valido() -> None:
    assert _metrics().total_km == 42.0


def test_metrics_rejeita_negativo() -> None:
    with pytest.raises(ValidationError):
        _metrics(total_km=-1)


def test_gain_percent() -> None:
    assert gain_percent(100, 80) == pytest.approx(20)
    assert gain_percent(100, 120) == pytest.approx(-20)
    with pytest.raises(ValueError):
        gain_percent(0, 10)


def test_compute_metrics_lista_vazia_sem_divisao_por_zero() -> None:
    metrics = compute_metrics([])
    assert metrics.total_km == 0
    assert metrics.avg_eta_min == 0
    assert metrics.avg_orders_per_route == 0
    assert metrics.gain_vs_manual_km is None
