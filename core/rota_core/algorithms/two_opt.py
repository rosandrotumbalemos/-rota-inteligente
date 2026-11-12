"""Melhoria local 2-opt da ordem de visita de uma rota com início e fim fixos (depósito).

Um movimento 2-opt escolhe um trecho ``seq[i..j]`` e inverte sua ordem. Na rota
``depósito -> a -> b -> ... -> c -> d -> depósito``, inverter ``b..c`` troca as ligações
``a->b`` e ``c->d`` por ``a->c`` e ``b->d``, desfazendo "cruzamentos".

Regra de aceitação: o custo total da rota candidata é recalculado por inteiro e o movimento só
é aceito se for estritamente menor (com tolerância numérica). Recalcular tudo, e não apenas as
duas ligações trocadas, mantém a garantia mesmo em grafos dirigidos, onde o trecho invertido
pode ter custo diferente no sentido contrário (mão única). Logo, o 2-opt nunca piora a rota.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")
CostFn = Callable[[T, T], float]

EPSILON = 1e-9


def tour_cost(sequence: Sequence[T], cost: CostFn, depot: T) -> float:
    """Custo de ``depósito -> sequence... -> depósito``."""
    tour = [depot, *sequence, depot]
    return sum(cost(u, v) for u, v in zip(tour, tour[1:], strict=False))


def two_opt(
    sequence: Sequence[T],
    cost: CostFn,
    depot: T,
    max_passes: int = 100,
) -> list[T]:
    """Aplica 2-opt (primeira melhoria) até não haver ganho ou atingir ``max_passes``.

    Args:
        sequence: ordem inicial dos pontos (sem o depósito).
        cost: custo dirigido entre dois pontos, por exemplo o custo A* em km.
        depot: ponto de partida e chegada, fixo.
        max_passes: limite de varreduras completas (proteção contra laços longos).

    Returns:
        Nova lista com os mesmos pontos; custo <= custo da ordem inicial.
    """
    best = list(sequence)
    if len(best) < 2:
        return best
    best_cost = tour_cost(best, cost, depot)

    for _ in range(max_passes):
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                candidate = best[:i] + best[i : j + 1][::-1] + best[j + 1 :]
                candidate_cost = tour_cost(candidate, cost, depot)
                if candidate_cost < best_cost - EPSILON:
                    best, best_cost, improved = candidate, candidate_cost, True
        if not improved:
            break
    return best
