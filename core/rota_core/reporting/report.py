"""Pipeline de resultados: executa as estratégias, calcula métricas, gera mapas, gráficos,
``comparison.csv`` e ``report.md``.

A interpretação dos resultados é escrita a partir dos números da execução: se o K-Means + A*
perder para o vizinho mais próximo em algum critério, o relatório diz isso e aponta a causa
provável, em vez de usar um texto fixo.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from rota_core.algorithms.assignment import snap_orders_to_nodes
from rota_core.algorithms.kmeans_astar import KMeansAStarPlan
from rota_core.algorithms.kmeans_zones import evaluate_k, zone_capacity
from rota_core.algorithms.routing import cached_astar
from rota_core.data.loaders import Dataset
from rota_core.domain.models import NodeKind, Strategy
from rota_core.graph.city_graph import depot_id, haversine_km
from rota_core.reporting.charts import generate_charts
from rota_core.reporting.maps import generate_maps
from rota_core.services.benchmark import BenchmarkResult, run_benchmark
from rota_core.services.metrics import (
    STRATEGY_LABELS,
    ComparisonReport,
    compare_strategies,
    describe_change,
    fmt_br,
)
from rota_core.services.optimizer import OptimizationResult, optimize

MANUAL = Strategy.MANUAL.value
NN = Strategy.NEAREST_NEIGHBOR.value
KM = Strategy.KMEANS_ASTAR.value
K_RANGE = range(2, 9)


@dataclass
class ReportArtifacts:
    """Tudo o que foi gerado, para o CLI e os testes."""

    out_dir: Path
    comparison: ComparisonReport
    optimization: OptimizationResult
    k_evaluation: list[dict[str, float]]
    benchmark: BenchmarkResult | None
    paths: dict[str, Path] = field(default_factory=dict)


def _pct(a: float, b: float) -> float:
    """Diferença percentual de ``a`` em relação a ``b`` (positivo = ``a`` maior)."""
    return (a - b) / b * 100 if b else 0.0


def write_comparison_csv(report: ComparisonReport, path: Path) -> Path:
    rows = report.rows()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in row.items()}
            )
    return path


def _routes_table(report: ComparisonReport, name: str) -> str:
    lines = [
        "| Entregador | Zona | Pedidos | km | min | R$ | ETA médio (min) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for rm in report.route_metrics[name]:
        zone = "—" if rm.cluster_label is None else str(rm.cluster_label)
        lines.append(
            f"| {rm.courier_id} | {zone} | {rm.orders_count} | {fmt_br(rm.km, 2)} "
            f"| {fmt_br(rm.minutes)} | {fmt_br(rm.cost, 2)} | {fmt_br(rm.avg_eta_min)} |"
        )
    return "\n".join(lines)


def zone_access(opt: OptimizationResult) -> dict[int, dict[str, float]]:
    """Para cada zona: distância do depósito ao pedido mais próximo, pelas ruas (A*) e em
    linha reta, e a razão entre as duas (quanto a malha viária "alonga" o acesso)."""
    plan = opt.kmeans_plan
    if plan is None:
        return {}
    graph = opt.graph
    depot = depot_id(graph)
    d_lat, d_lon = graph.nodes[depot]["lat"], graph.nodes[depot]["lon"]
    access = {}
    for zone in plan.zones:
        road = min(
            cached_astar(graph, depot, o.node_id, "distance_km").total_distance_km
            if o.node_id != depot
            else 0.0
            for o in zone.orders
        )
        straight = min(haversine_km(d_lat, d_lon, o.lat, o.lon) for o in zone.orders)
        access[zone.cluster_id] = {
            "road_km": road,
            "straight_km": straight,
            "ratio": road / straight if straight else 1.0,
        }
    return access


def _far_zone_note(opt: OptimizationResult) -> str:
    plan: KMeansAStarPlan | None = opt.kmeans_plan
    if plan is None:
        return ""
    access = zone_access(opt)
    far = max(plan.zones, key=lambda z: plan.zone_km[z.cluster_id])
    a = access[far.cluster_id]
    others = [v["ratio"] for c, v in access.items() if c != far.cluster_id] or [1.0]
    return (
        f"A zona mais cara é a **zona {far.cluster_id}** ({far.size} pedidos, "
        f"{fmt_br(plan.zone_km[far.cluster_id])} km, entregador "
        f"{plan.assignment[far.cluster_id]}). Em linha reta, o pedido mais próximo dela fica a "
        f"{fmt_br(a['straight_km'])} km do depósito; pelas ruas, a {fmt_br(a['road_km'])} km "
        f"({fmt_br(a['ratio'])}× mais, contra {fmt_br(min(others))}–{fmt_br(max(others))}× nas "
        "outras zonas). A zona parece perto no mapa, mas não há ligação direta pelas ruas: é "
        "exatamente o que o K-Means não enxerga, porque agrupa por linha reta."
    )


def _vs(value: float, reference: float) -> str:
    """Variação de ``value`` em relação a ``reference`` na linguagem padronizada."""
    return describe_change(-_pct(value, reference))


def _interpretation(
    report: ComparisonReport,
    opt: OptimizationResult,
    bench: BenchmarkResult | None,
) -> str:
    """Interpretação gerada a partir dos números. Nunca afirma superioridade absoluta:
    resultados de um dataset são ditos "neste dataset" e a média vem do benchmark."""
    m = report.metrics
    if not {MANUAL, NN, KM} <= set(m):
        return "Interpretação disponível apenas com as três estratégias."
    km_vs_nn = _pct(m[KM].total_km, m[NN].total_km)
    mk_vs_nn = _pct(m[KM].max_route_min, m[NN].max_route_min)
    parts = [
        "1. **Otimizar vale muito.** Em relação à rota manual, o vizinho mais próximo tem "
        f"{describe_change(m[NN].gain_vs_manual_km)} em km e o K-Means + A*, "
        f"{describe_change(m[KM].gain_vs_manual_km)}. O ETA médio por pedido cai de "
        f"{fmt_br(m[MANUAL].avg_eta_min)} min para {fmt_br(m[NN].avg_eta_min)} e "
        f"{fmt_br(m[KM].avg_eta_min)} min. A rota manual cruza a cidade porque divide os pedidos "
        "pela ordem de chegada, não pela posição.",
    ]
    if km_vs_nn < -0.5:
        parts.append(
            "2. **Neste dataset, o K-Means + A* é o melhor em distância:** "
            f"{_vs(m[KM].total_km, m[NN].total_km)} em km em relação ao vizinho mais próximo "
            f"({_vs(m[KM].total_min, m[NN].total_min)} em tempo)."
        )
    elif km_vs_nn <= 0.5:
        parts.append(
            "2. **Neste dataset, K-Means + A* e vizinho mais próximo empatam em distância** "
            f"({_vs(m[KM].total_km, m[NN].total_km)} em km para o K-Means + A*). Em tempo "
            f"total, o K-Means + A* tem {_vs(m[KM].total_min, m[NN].total_min)}."
        )
    else:
        parts.append(
            "2. **Neste dataset, o K-Means + A* perde para o vizinho mais próximo:** "
            f"{_vs(m[KM].total_km, m[NN].total_km)} em km e "
            f"{_vs(m[KM].total_min, m[NN].total_min)} em tempo."
        )
    if mk_vs_nn > 5:
        parts.append(
            "3. **A rota mais longa é pior no K-Means + A*** "
            f"({fmt_br(m[KM].max_route_min)} contra {fmt_br(m[NN].max_route_min)} min, "
            f"{_vs(m[KM].max_route_min, m[NN].max_route_min)}). " + _far_zone_note(opt)
        )
    else:
        parts.append(
            f"3. **A rota mais longa** do K-Means + A* tem {fmt_br(m[KM].max_route_min)} min, "
            f"contra {fmt_br(m[NN].max_route_min)} min do vizinho mais próximo "
            f"({_vs(m[KM].max_route_min, m[NN].max_route_min)})."
        )
    cheapest = report.best("custo")
    parts.append(
        f"4. **Custo:** o mais barato é {STRATEGY_LABELS[cheapest]} "
        f"(R$ {fmt_br(m[cheapest].total_cost, 2)}). No K-Means + A*, a atribuição húngara "
        "entrega a zona mais longa ao entregador com menor custo por km. Como o modelo não muda "
        "a velocidade por veículo, isso reduz o custo em R$, mas não o km nem o tempo: os km de "
        "cada zona são os mesmos, seja quem for o entregador."
    )
    parts.append(
        f"5. **Balanceamento:** desvio de pedidos por entregador de {fmt_br(m[NN].balance_std, 2)} "
        f"(vizinho, cotas fixas) e {fmt_br(m[KM].balance_std, 2)} (K-Means). O K-Means aceita "
        "zonas desiguais (até a média + 2 pedidos) em troca de zonas compactas. Número igual de "
        "pedidos não significa trabalho igual: a carga real aparece em minutos no gráfico de carga."
    )
    if bench and bench.seeds:
        a = bench.averages
        parts.append(
            f"6. **Um dataset não basta.** Na média de {bench.seeds} datasets sintéticos, o "
            f"K-Means + A* tem {_vs(a[KM]['total_km'], a[NN]['total_km'])} em km e "
            f"{_vs(a[KM]['max_route_min'], a[NN]['max_route_min'])} na maior rota em relação "
            f"ao vizinho mais próximo. Ele percorre menos km em {bench.kmeans_wins_km} de "
            f"{bench.seeds} datasets e tem a maior rota mais curta em "
            f"{bench.kmeans_wins_makespan} de {bench.seeds}. Conclusão: **é a melhor estratégia "
            "em média, mas não em todos os casos**. Perde quando a proximidade em linha reta não "
            "corresponde à proximidade pelas ruas, ou quando uma zona compacta tem acesso difícil "
            "a partir do depósito."
        )
    else:
        parts.append(
            "6. **Este resultado vale para um único dataset.** Rode o relatório com "
            "`--benchmark-seeds 30` para ver a média em vários cenários antes de concluir qual "
            "estratégia é melhor em geral."
        )
    return "\n".join(parts)


def _benchmark_table(bench: BenchmarkResult) -> str:
    lines = [
        "| Estratégia (média) | km | min | R$ | ETA médio (min) | Maior rota (min) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, a in bench.averages.items():
        lines.append(
            f"| {STRATEGY_LABELS[name]} | {fmt_br(a['total_km'], 2)} | {fmt_br(a['total_min'])} "
            f"| {fmt_br(a['total_cost'], 2)} | {fmt_br(a['avg_eta_min'])} "
            f"| {fmt_br(a['max_route_min'])} |"
        )
    return "\n".join(lines)


def build_report_markdown(
    dataset: Dataset,
    opt: OptimizationResult,
    report: ComparisonReport,
    k_eval: list[dict[str, float]],
    bench: BenchmarkResult | None,
    paths: dict[str, Path],
    out_dir: Path,
    seed: int,
    max_extra: int,
) -> str:
    graph = opt.graph
    n_nodes = graph.number_of_nodes()
    n_streets = len(dataset.edges)
    street_km = sum(e.distance_km for e in dataset.edges)
    speeds = sorted({e.speed_kmh for e in dataset.edges})
    active = [c for c in dataset.couriers if c.active]
    plan = opt.kmeans_plan
    k_used = len(plan.zones) if plan else len(active)
    best_sil = max(k_eval, key=lambda e: e["silhouette"]) if k_eval else None
    used_sil = next((e for e in k_eval if e["k"] == k_used), None)
    created = sorted(o.created_at for o in dataset.orders)

    def img(key: str, alt: str) -> str:
        return f"![{alt}]({paths[key].relative_to(out_dir).as_posix()})" if key in paths else ""

    zones_line = ""
    if plan:
        sizes = ", ".join(f"zona {z.cluster_id}: {z.size}" for z in plan.zones)
        zones_line = f"Zonas finais: {sizes} pedidos (limite {zone_capacity(len(dataset.orders), k_used, max_extra)})."

    sil_text = ""
    if best_sil and used_sil:
        sil_text = (
            f"Com k = {k_used} (número de entregadores), a silhueta é {fmt_br(used_sil['silhouette'], 2)}; "
            f"a maior silhueta é {fmt_br(best_sil['silhouette'], 2)}, com k = {best_sil['k']}. "
            "O k usado segue a frota disponível, não o ótimo geométrico: cada zona precisa de um "
            "entregador."
        )

    bench_section = "Benchmark desativado nesta execução (`--benchmark-seeds 0`)."
    if bench and bench.seeds:
        bench_section = (
            f"As três estratégias foram executadas em {bench.seeds} datasets gerados com seeds "
            f"1 a {bench.seeds} (outra cidade e outros pedidos em cada um), peso `{bench.weight}`.\n\n"
            + _benchmark_table(bench)
            + f"\n\nK-Means + A* com menos km que o vizinho mais próximo: **{bench.kmeans_wins_km} de "
            f"{bench.seeds}**. Com maior rota mais curta: **{bench.kmeans_wins_makespan} de "
            f"{bench.seeds}**."
        )

    return f"""# Relatório — Rota Inteligente (Sabor Express)

Gerado por `python -m rota_core report` em {date.today().isoformat()} · peso de otimização: `{opt.weight}` · `random_state` do K-Means: {seed}

## 1. Objetivo

Sugerir rotas de entrega mais curtas, rápidas e baratas para a Sabor Express, que hoje divide os pedidos e define os trajetos manualmente. A cidade é tratada como um **grafo**. Três estratégias são comparadas com as mesmas métricas: a rota manual (como é feito hoje), o vizinho mais próximo e o K-Means + A*.

## 2. Metodologia

1. Carregar e validar os CSVs (nós, ruas, pedidos, entregadores).
2. Montar o grafo dirigido (cada rua de mão dupla vira dois arcos) e ligar cada pedido ao nó mais próximo (*snap* por Haversine).
3. Executar cada estratégia num grafo novo, com o cache de A* vazio, medindo o tempo de cálculo.
4. Calcular métricas por rota e por estratégia; comparar com a rota manual.
5. Repetir as três estratégias em {bench.seeds if bench else 0} datasets gerados (teste de robustez).

Condições iguais para todas: mesmo grafo, mesmos pedidos e entregadores, mesmo A* (validado contra o Dijkstra), mesmo peso.

## 3. O grafo

{img("graph_map", "Grafo da cidade")}

- **{n_nodes} nós:** 1 depósito (a cozinha, Praça da Sé) e {n_nodes - 1} bairros/pontos no centro de São Paulo.
- **{n_streets} ruas de mão dupla** ({graph.number_of_edges()} arcos), somando {fmt_br(street_km)} km.
- **Peso de cada aresta:** distância em km (linha reta × fator de desvio de 1,15 a 1,40) e tempo em minutos = distância / velocidade × 60, com velocidades de {", ".join(f"{s:g}" for s in speeds)} km/h.
- O grafo é conexo: todo ponto é alcançável a partir do depósito.

## 4. Os dados

| Arquivo | Conteúdo |
| --- | --- |
| `nodes.csv` | {n_nodes} nós (`id, name, kind, lat, lon`); depósito `{next(n.id for n in dataset.nodes if n.kind == NodeKind.DEPOT)}` |
| `edges.csv` | {n_streets} ruas (`source, target, distance_km, speed_kmh, oneway`) |
| `orders.csv` | {len(dataset.orders)} pedidos fictícios, de {created[0]:%H:%M} a {created[-1]:%H:%M} (pico do almoço) |
| `couriers.csv` | {len(active)} entregadores ativos: {", ".join(f"{c.id} ({c.vehicle}, R$ {fmt_br(c.cost_per_km, 2)}/km)" for c in active)} |

Todos os dados são fictícios e gerados com seed fixa; nenhum dado pessoal real.

## 5. Algoritmos

**A\\*** — menor caminho entre dois nós expandindo sempre o nó de menor `f(n) = g(n) + h(n)`, em que `g` é o custo já percorrido e `h` é a estimativa do que falta. A heurística é a distância Haversine até o destino (peso em km) ou essa distância dividida pela velocidade máxima da malha (peso em minutos). Ela nunca superestima, porque nenhuma rua é mais curta que a linha reta, então o caminho é ótimo. Validado contra o Dijkstra em 250 pares para cada peso.

**K-Means** — agrupa os pedidos em k = {k_used} zonas pela posição (latitude/longitude convertidas em km). Cada pedido vai para o centróide mais próximo; os centróides são recalculados até estabilizar (`n_init=10`, `random_state={seed}`). {sil_text}

**Balanceamento** — o K-Means não controla o tamanho dos grupos. Nenhuma zona pode passar de `ceil(n/k) + {max_extra}` pedidos; o excedente sai pelos pedidos "de borda", que estão quase tão perto de uma zona vizinha. Nenhuma zona fica vazia. {zones_line}

**Atribuição húngara** — cada zona vai para um entregador diferente, minimizando o custo total: `km da zona × custo/km do entregador`. A solução ótima vem do `scipy.optimize.linear_sum_assignment`.

**Vizinho mais próximo + 2-opt** — dentro de cada zona, a ordem inicial vai sempre ao pedido mais próximo (custo A*). O 2-opt inverte trechos da sequência para desfazer cruzamentos e só aceita uma troca se o custo total da rota diminuir. Logo, nunca piora a rota.

**Baselines** — *manual*: pedidos em ordem de chegada, distribuídos em rodízio, visitados na ordem de chegada. *Vizinho mais próximo*: cotas iguais por entregador; cada um sai do depósito e vai sempre ao pedido livre mais próximo.

## 6. Resultados

### Tabela comparativa

{report.markdown_table()}

Variação em relação à rota manual: "redução" = a estratégia é melhor; "aumento" = é pior. ETA = minutos desde a saída do depósito até a chegada ao pedido. Desvio de carga = desvio-padrão do número de pedidos por entregador. O tempo de cálculo varia entre execuções.

### Rankings

{report.ranking_markdown()}

### Rotas por estratégia

**Manual**

{_routes_table(report, MANUAL) if MANUAL in report.route_metrics else ""}

**Vizinho mais próximo**

{_routes_table(report, NN) if NN in report.route_metrics else ""}

**K-Means + A\\***

{_routes_table(report, KM) if KM in report.route_metrics else ""}

## 7. Interpretação

{_interpretation(report, opt, bench)}

### Robustez

{bench_section}

## 8. Mapas

{img("comparison_map", "Comparação das rotas")}

{img("zones_map", "Zonas do K-Means")}

| Rota manual | Vizinho mais próximo | K-Means + A* |
| --- | --- | --- |
| {img("routes_manual", "Rotas manual")} | {img("routes_nearest_neighbor", "Rotas vizinho")} | {img("routes_kmeans_astar", "Rotas K-Means")} |

## 9. Gráficos

{img("distance_comparison", "Distância")}

{img("time_comparison", "Tempo")}

{img("cost_comparison", "Custo")}

{img("route_load", "Carga por entregador")}

{img("execution_time", "Tempo de cálculo")}

{img("kmeans_elbow", "Cotovelo")}

{img("kmeans_silhouette", "Silhueta")}

## 10. Limitações

- **O K-Means não conhece a malha viária.** Agrupa por proximidade em linha reta; dois pedidos vizinhos no mapa podem estar longe pelas ruas.
- **O K-Means ignora o depósito.** Uma zona compacta, mas de acesso difícil a partir do depósito, gera uma rota longa.
- **Velocidades fixas por rua**, sem trânsito real, semáforos nem variação por horário.
- **O veículo não muda a velocidade**, por isso a atribuição húngara afeta só o custo em R$.
- **Sem capacidade de carga nem janela de horário** (os campos existem no modelo, mas ainda não são usados).
- **Grafo sintético e pequeno** ({n_nodes} nós), com dados fictícios.
- **O balanceamento usa o número de pedidos**, não a duração das rotas.

## 11. Sugestões de melhoria

1. **Considerar o depósito no agrupamento:** agrupar por ângulo e distância a partir do depósito (método *sweep*) ou acrescentar essa distância às coordenadas.
2. **Agrupar por distância de rua**, usando K-Medoids sobre a matriz de custos A*.
3. **Trocas entre zonas** após o roteamento (*relocate/exchange*), balanceando pela duração das rotas.
4. **Escolher k pelo custo total** (testar k = 2 a {len(active)}) em vez de fixar k = número de entregadores.
5. **Capacidade, prioridade e janelas de horário** (VRP com restrições, ex.: OR-Tools).
6. **Dados reais do OpenStreetMap** e velocidades por horário para representar o pico.
"""


def generate_report(
    dataset: Dataset,
    out_dir: Path,
    weight: str = "distance_km",
    k: int | None = None,
    seed: int = 42,
    max_extra: int = 2,
    benchmark_seeds: int = 30,
) -> ReportArtifacts:
    """Executa tudo e grava ``maps/``, ``charts/``, ``comparison.csv`` e ``report.md``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    opt = optimize(dataset, weight=weight, k=k, seed=seed, max_extra=max_extra)
    couriers = sorted(c.id for c in dataset.couriers if c.active)
    comparison = compare_strategies(opt.routes, opt.compute_ms, n_couriers=len(couriers))

    snapped = snap_orders_to_nodes(opt.graph, dataset.orders)
    k_eval = evaluate_k(snapped, K_RANGE, seed=seed)
    k_used = len(opt.kmeans_plan.zones) if opt.kmeans_plan else len(couriers)

    paths: dict[str, Path] = {}
    paths.update(generate_maps(opt.graph, snapped, opt.routes, opt.kmeans_plan, couriers, out_dir))
    paths.update(generate_charts(comparison, couriers, k_eval, k_used, out_dir))
    paths["comparison_csv"] = write_comparison_csv(comparison, out_dir / "comparison.csv")

    bench = None
    if benchmark_seeds > 0:
        bench = run_benchmark(benchmark_seeds, weight, k, seed, max_extra)

    markdown = build_report_markdown(
        dataset, opt, comparison, k_eval, bench, paths, out_dir, seed, max_extra
    )
    report_path = out_dir / "report.md"
    report_path.write_text(markdown, encoding="utf-8")
    paths["report"] = report_path
    return ReportArtifacts(
        out_dir=out_dir,
        comparison=comparison,
        optimization=opt,
        k_evaluation=k_eval,
        benchmark=bench,
        paths=paths,
    )
