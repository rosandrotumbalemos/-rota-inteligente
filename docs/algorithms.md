# Algoritmos

Este documento explica cada algoritmo do núcleo de IA: o que faz, um exemplo curto com os dados do projeto, a garantia que oferece e quanto custa computacionalmente.

## Visão geral

| Ordem | Algoritmo | Pergunta que responde | Código |
| --- | --- | --- | --- |
| 1 | Snap (Haversine) | Em que nó do grafo fica cada pedido? | `algorithms/assignment.py` |
| 2 | **K-Means** | Quais pedidos formam uma zona? | `algorithms/kmeans_zones.py` |
| 3 | **Balanceamento** | Alguma zona ficou grande demais? | `algorithms/kmeans_zones.py` |
| 4 | Vizinho mais próximo | Em que ordem visitar os pedidos da zona? | `algorithms/nearest_neighbor.py` |
| 5 | **2-opt** | Dá para melhorar essa ordem? | `algorithms/two_opt.py` |
| 6 | **Atribuição húngara** | Qual entregador fica com qual zona? | `algorithms/assignment.py` |
| 7 | **A\*** | Qual o menor caminho entre dois pontos? | `algorithms/astar.py` |

O pipeline completo fica em `algorithms/kmeans_astar.py`. Os passos 4 e 5 vêm antes do 6 porque a atribuição precisa saber quantos km cada zona tem.

**Notação de complexidade:** V = nós do grafo (40), E = arcos (120), P = pedidos (20), k = zonas/entregadores (4), m = pedidos numa zona (3 a 7). "O(n²)" significa que o trabalho cresce com o quadrado de n: dobrar n quadruplica o tempo.

## Representação do problema

- Grafo dirigido `G = (V, E)`. Cada rua de mão dupla vira dois arcos; uma rua de mão única vira um só.
- Peso de um arco: `distance_km`, ou `time_min = distance_km / speed_kmh × 60`.
- O grafo é montado com NetworkX (`graph/city_graph.py`), mas o A* foi implementado no projeto.

## 1. Snap dos pedidos

Os pedidos têm latitude e longitude livres, mas o A* só anda entre nós. O snap liga cada pedido ao nó mais próximo pela distância Haversine (linha reta sobre a Terra). Em caso de empate, vence o menor id. A função devolve cópias novas dos pedidos; os originais não mudam.

**Exemplo:** no dataset, os 20 pedidos caem em 15 nós diferentes, a 108 m do nó em média (máximo 160 m).

**Complexidade:** O(P × V): cada pedido é comparado com todos os nós. São 800 cálculos, instantâneo.

## 2. A\* (menor caminho)

O A* expande sempre o nó com menor

```latex
f(n) = g(n) + h(n)
```

- `g(n)`: custo real já percorrido da origem até `n`.
- `h(n)`: estimativa do custo que falta até o destino (a heurística).

Passo a passo: a origem entra numa fila de prioridade (`heapq`). O algoritmo retira o nó de menor `f`; se for o destino, reconstrói o caminho. Senão, atualiza os vizinhos cujo custo melhorou e os coloca na fila. Fila vazia sem chegar ao destino gera `NoPathError`.

**Heurística admissível:** uma heurística é admissível quando nunca superestima o custo real; com ela, o A* garante o caminho ótimo.

| Peso | Heurística `h(n)` | Por que nunca superestima |
| --- | --- | --- |
| `distance_km` | Haversine até o destino | Nenhuma rua é mais curta que a linha reta entre seus extremos |
| `time_min` | Haversine / `v_max` × 60 (`v_max` = 40 km/h) | Nenhum trajeto é mais rápido que a linha reta na velocidade máxima da malha |

A heurística também é **consistente** (`h(u) ≤ w(u, v) + h(v)` em todo arco). Isso garante que um nó retirado da fila já tem seu custo ótimo. As duas propriedades são verificadas nos testes para todos os pares de nós.

**Exemplo:** do depósito N00 ao N01, o caminho é `N00 → N17 → N06 → N26 → N19 → N02 → N12 → N05 → N01` (8,0 km, 15,4 min). Em 250 pares aleatórios, o A* expandiu em média 14,5 nós por busca, contra 21,1 do Dijkstra, com o mesmo custo final.

**Complexidade:** no pior caso, O((V + E) log V), igual ao Dijkstra com fila de prioridade. Na prática, a heurística evita boa parte dos nós. O Dijkstra é o A* com `h = 0`.

**Cache:** cada resultado é guardado por `(origem, destino, peso)` dentro do próprio grafo, e um trecho repetido custa O(1). No K-Means + A*, 66 trechos são calculados e reaproveitados 383 vezes (o 2-opt reavalia os mesmos trechos muitas vezes).

**Limitações:**
- A heurística de tempo é fraca quando a maioria das ruas é mais lenta que `v_max`: em média, 16,0 nós expandidos, contra 21,0 do Dijkstra.
- As velocidades são fixas, sem trânsito.
- Uma rua cadastrada com distância menor que a linha reta quebraria a garantia.
- O A* resolve um trecho entre dois pontos; a ordem de várias entregas é resolvida pelos outros algoritmos.

## 3. K-Means (agrupamento em zonas)

O K-Means separa os pedidos em k grupos:

1. Escolhe k centróides iniciais.
2. Associa cada pedido ao centróide mais próximo.
3. Move cada centróide para a média dos seus pedidos.
4. Repete os passos 2 e 3 até estabilizar.

O projeto usa `KMeans(n_init=10, random_state=42)` do scikit-learn. O algoritmo roda 10 vezes com inícios diferentes e fica com a melhor execução; o `random_state` fixo torna o resultado determinístico.

- **Projeção em km:** antes do agrupamento, latitude e longitude são convertidas em km. Em São Paulo, 1° de longitude mede cerca de 0,92 de 1° de latitude, então agrupar em graus distorceria o mapa.
- **Escolha de k:** k = número de entregadores ativos (4). Os gráficos de cotovelo e silhueta (k = 2 a 8) confirmam que 4 é uma boa escolha: o cotovelo fica em 4 e a silhueta de 4 (0,52) é quase igual à melhor (0,53, k = 6).

**Exemplo:** os 20 pedidos formam zonas de 8, 7, 2 e 3 pedidos.

**Complexidade:** O(n_init × iterações × P × k). Com 20 pedidos e k = 4, são poucos milhares de operações.

**Limitação central: o K-Means não conhece a malha viária.** Ele mede a proximidade em linha reta. Dois pedidos vizinhos no mapa podem estar longe pelas ruas, por falta de ligação direta ou por mão única, e mesmo assim cairão na mesma zona. Ele também não considera o depósito.

**O caso da zona 0:** no dataset oficial, o pedido mais próximo da zona 0 (oeste) fica a 1,5 km do depósito em linha reta, mas a 6,6 km pelas ruas (4,3×). Nas outras zonas, essa razão é de 1,4× a 2,2×. A zona é compacta no mapa, mas cara de acessar, e fecha com 35,3 km. O A* calcula o caminho real, mas só depois que a zona já foi formada.

## 4. Balanceamento das zonas

O K-Means não controla o tamanho dos grupos. Regra do projeto: nenhuma zona pode passar de `ceil(n/k) + 2` pedidos.

Enquanto a maior zona passar do limite, sai dela o pedido "de borda" mais barato, ou seja, o que minimiza `dist(pedido, centróide da zona vizinha) − dist(pedido, centróide atual)`. Ele vai para uma zona com vaga. No fim, os centróides são recalculados.

**Exemplo:** limite = ceil(20/4) + 2 = 7. A zona de 8 pedidos cede 1 pedido, e as zonas finais ficam com 7, 7, 3 e 3.

**Garantias:** nenhuma zona fica vazia (só zonas acima do limite cedem pedidos), cada pedido continua em exatamente uma zona e o resultado é determinístico.

**Complexidade:** O(movimentos × m × k). Cada movimento avalia os pedidos da zona cheia contra as zonas com vaga.

**Limitação:** conta pedidos, não minutos, e limita só o tamanho máximo das zonas.

## 5. Vizinho mais próximo (ordem inicial e baseline)

A partir do ponto atual, vai sempre ao pedido ainda não visitado de menor custo A* (empate: menor id).

- **Dentro de uma zona** (K-Means + A*): dá a ordem inicial, que o 2-opt depois tenta melhorar.
- **Como estratégia própria** (baseline): sem zonas e com cotas iguais (20 pedidos → 5 por entregador). Os entregadores são roteirizados um de cada vez; os primeiros pegam os pedidos mais próximos e os últimos ficam com o que sobrou.

**Exemplo:** o entregador E01 sai do depósito e vai primeiro ao P016, o pedido livre mais próximo pelas ruas.

**Complexidade:** O(P²) comparações de custo, cada uma lida do cache do A*.

## 6. 2-opt (melhoria da ordem)

Um movimento 2-opt inverte um trecho da sequência: `D → A → B … C → E → D` vira `D → A → C … B → E → D`. Isso desfaz "cruzamentos" no trajeto.

**Regra de aceitação:** o custo total da rota candidata é recalculado por inteiro, e a troca só é aceita se for estritamente menor. Recalcular tudo mantém a garantia mesmo com mão única, em que inverter um trecho muda seu custo. Logo, **o 2-opt nunca piora a rota**.

**Exemplo:** depósito em (0,0) e pedidos em A (0,1), B (1,1) e C (1,0). A ordem B → A → C cruza o próprio caminho e custa 4,83. O 2-opt inverte o trecho e chega a A → B → C, que custa 4,00.

**Efeito medido:** no dataset oficial, nenhuma melhoria, porque as zonas são pequenas e a ordem inicial já não tinha cruzamentos. Em 30 datasets, melhorou 33 de 120 zonas, com redução de 1,4% do km dessas rotas.

**Complexidade:** O(m²) trocas candidatas por passada, cada uma avaliada em O(m), ou seja, O(m³) por passada. Com m ≤ 7, são algumas centenas de operações.

## 7. Atribuição húngara (zona → entregador)

Monta uma matriz `custo[zona][entregador] = km da zona × custo/km do entregador` e encontra a combinação de menor custo total com `scipy.optimize.linear_sum_assignment`. Cada zona vai para um entregador diferente. O resultado é ótimo (testado contra força bruta em todas as permutações).

**Exemplo:** zona 0 (35,3 km) e zona 3 (10,3 km); moto a R$ 0,42/km e bike a R$ 0,10/km.

| Atribuição | Custo |
| --- | --- |
| Bike → zona 0, moto → zona 3 | 35,3 × 0,10 + 10,3 × 0,42 = **R$ 7,86** |
| Moto → zona 0, bike → zona 3 | 35,3 × 0,42 + 10,3 × 0,10 = R$ 15,86 |

Nas duas opções, o total é o mesmo: 45,6 km. **A atribuição reduz o custo em R$, mas não muda o km nem o tempo:** os km de cada zona não dependem de quem a percorre, e no modelo todos os veículos andam na mesma velocidade e saem do mesmo depósito. A estrutura fica pronta para custos mais ricos, como velocidade por veículo.

**Complexidade:** O(k³). Com k = 4, é instantâneo.

## 8. Rota manual (baseline)

Simula o processo atual: pedidos em ordem de chegada, distribuídos em rodízio (1º → E01, 2º → E02, …, 5º → E01) e visitados na ordem de chegada. Os trechos usam o A*: o entregador conhece as ruas, mas a divisão e a ordem não são otimizadas.

**Complexidade:** O(P log P) para ordenar, mais um A* por trecho.

## 9. Métricas

Código: `services/metrics.py`.

| Métrica | Definição |
| --- | --- |
| `total_km`, `total_min`, `total_cost` | Soma das rotas; custo = km × custo/km do entregador (R$) |
| `avg_eta_min` | Média, **por pedido**, dos minutos desde a saída do depósito até a chegada |
| `max_route_min` | Duração da rota mais longa: quando o último entregador volta |
| `balance_std` | Desvio-padrão do número de pedidos por entregador (0 = carga igual) |
| `compute_ms` | Tempo de cálculo da estratégia, medido num grafo com cache vazio |
| `orders_count`, `routes_count`, `avg_orders_per_route` | Contagens |
| `gain_vs_manual_km/min/cost` | `(manual − estratégia) / manual × 100` |

**Como ler a variação em relação à manual:** valor positivo = **redução** (a estratégia gasta menos km, tempo ou custo); valor negativo = **aumento** (gasta mais). Nos textos e tabelas, os valores aparecem sempre como "redução de X%" ou "aumento de X%". Sem rota manual ou com base zero, o campo fica vazio (`None`).

As métricas são determinísticas, exceto `compute_ms`, e funcionam igual para `distance_km` e `time_min`.

**Complexidade:** O(P), uma passada pelas rotas.

## Custo total do pipeline

Para 20 pedidos, o K-Means + A* inteiro leva cerca de 8 a 20 ms; o vizinho mais próximo, cerca de 6 ms; a manual, cerca de 2 ms. A maior parte do tempo vai para o A* (primeira vez de cada trecho) e para o K-Means com 10 inicializações. Com muito mais pedidos, os gargalos seriam a matriz A* (até P² trechos) e o 2-opt em zonas grandes.
