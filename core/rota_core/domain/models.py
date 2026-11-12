"""Modelos de domínio (Pydantic v2), sem dependência de API ou banco de dados."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NodeKind(StrEnum):
    DEPOT = "depot"
    BAIRRO = "bairro"


class Vehicle(StrEnum):
    MOTO = "moto"
    BIKE = "bike"


class Strategy(StrEnum):
    MANUAL = "manual"
    NEAREST_NEIGHBOR = "nearest_neighbor"
    KMEANS_ASTAR = "kmeans_astar"


class Weight(StrEnum):
    DISTANCE = "distance"
    TIME = "time"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    FAILED = "failed"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Node(_Model):
    """Ponto da cidade: o depósito (cozinha) ou um bairro/ponto de entrega."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: NodeKind
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Edge(_Model):
    """Rua entre dois nós. O tempo é derivado da distância e da velocidade média."""

    source: str
    target: str
    distance_km: float = Field(gt=0)
    speed_kmh: float = Field(gt=0)
    oneway: bool = False

    @model_validator(mode="after")
    def _no_self_loop(self) -> Edge:
        if self.source == self.target:
            raise ValueError(f"aresta com origem e destino iguais: {self.source}")
        return self

    @property
    def time_min(self) -> float:
        return self.distance_km / self.speed_kmh * 60


class Order(_Model):
    """Pedido fictício a ser entregue."""

    id: str
    code: str
    customer_alias: str
    address_label: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    created_at: datetime
    value: float = Field(ge=0)
    node_id: str | None = None  # preenchido no "snap" ao nó mais próximo (próxima etapa)
    status: DeliveryStatus = DeliveryStatus.PENDING
    # Campos opcionais para restrições futuras (capacidade, prioridade e janela de entrega).
    weight_kg: float | None = Field(default=None, ge=0)
    priority: str | None = None
    janela_inicio: datetime | None = None
    janela_fim: datetime | None = None

    @model_validator(mode="after")
    def _janela_valida(self) -> Order:
        if self.janela_inicio and self.janela_fim and self.janela_fim < self.janela_inicio:
            raise ValueError("janela_fim deve ser posterior a janela_inicio")
        return self


class Courier(_Model):
    """Entregador fictício."""

    id: str
    name: str
    vehicle: Vehicle
    cost_per_km: float = Field(ge=0)
    active: bool = True


class RouteStop(_Model):
    """Parada de uma rota, na ordem de visita."""

    order_id: str
    node_id: str
    seq: int = Field(ge=1)
    eta_min: float = Field(ge=0)
    cumulative_km: float = Field(ge=0)
    status: DeliveryStatus = DeliveryStatus.ASSIGNED


class Route(_Model):
    """Rota de um entregador: paradas ordenadas e caminho completo de nós no grafo."""

    courier_id: str
    strategy: Strategy
    cluster_label: int | None = None
    stops: list[RouteStop] = Field(default_factory=list)
    path: list[str] = Field(
        default_factory=list, description="Nós visitados, do depósito ao depósito."
    )
    total_km: float = Field(default=0, ge=0)
    total_min: float = Field(default=0, ge=0)
    total_cost: float = Field(default=0, ge=0)


class Metrics(_Model):
    """Métricas agregadas de uma execução de otimização."""

    total_km: float = Field(ge=0)
    total_min: float = Field(ge=0)
    total_cost: float = Field(ge=0)
    avg_eta_min: float = Field(ge=0)
    max_route_min: float = Field(ge=0, description="Makespan: duração da rota mais longa.")
    balance_std: float = Field(ge=0, description="Desvio-padrão de pedidos por entregador.")
    compute_ms: float = Field(ge=0)
    orders_count: int = Field(default=0, ge=0)
    routes_count: int = Field(default=0, ge=0)
    avg_orders_per_route: float = Field(default=0, ge=0)
    # Redução % em relação à rota manual (positivo = melhor; negativo = pior). None sem manual.
    gain_vs_manual_km: float | None = None
    gain_vs_manual_min: float | None = None
    gain_vs_manual_cost: float | None = None


class RouteMetrics(_Model):
    """Métricas de uma rota individual."""

    courier_id: str
    cluster_label: int | None = None
    orders_count: int = Field(ge=0)
    km: float = Field(ge=0)
    minutes: float = Field(ge=0)
    cost: float = Field(ge=0)
    avg_eta_min: float = Field(ge=0)
    last_eta_min: float = Field(ge=0, description="Chegada ao último pedido (antes do retorno).")


@dataclass(frozen=True)
class AStarResult:
    """Resultado de uma busca A* entre dois nós.

    ``total_cost`` está na unidade do peso otimizado (km para ``distance_km``, minutos para
    ``time_min``); ``total_distance_km`` e ``total_time_min`` são sempre somados no caminho.
    """

    path: list[str] = field(default_factory=list)
    total_cost: float = 0.0
    total_distance_km: float = 0.0
    total_time_min: float = 0.0
    weight: str = "distance_km"
    expanded_nodes: int = 0  # nós retirados da fila de prioridade (eficiência da busca)


@dataclass(frozen=True)
class Zone:
    """Zona de entrega: grupo de pedidos formado pelo K-Means (e ajustado no balanceamento)."""

    cluster_id: int
    centroid_lat: float
    centroid_lon: float
    orders: list[Order] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.orders)

    @property
    def order_ids(self) -> list[str]:
        return [o.id for o in self.orders]


class OptimizationRun(_Model):
    """Resultado de uma estratégia aplicada a um conjunto de pedidos."""

    id: str
    strategy: Strategy
    weight: Weight = Weight.DISTANCE
    k: int | None = Field(default=None, ge=1)
    created_at: datetime
    routes: list[Route] = Field(default_factory=list)
    metrics: Metrics | None = None
