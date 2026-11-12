# Resultados

Análise das três estratégias: rota manual, vizinho mais próximo e K-Means + A*. Os números vêm de `python -m rota_core report`, que também gera `outputs/report.md`, `outputs/comparison.csv`, os mapas e os gráficos. Todos os números são determinísticos, exceto o tempo de cálculo.

**Como ler as variações:** toda comparação usa a rota manual como referência (ou o vizinho mais próximo, quando indicado). "Redução de X%" significa que a estratégia gastou menos km, tempo ou custo, ou seja, foi melhor. "Aumento de X%" significa que gastou mais, ou seja, foi pior. No `comparison.csv`, os campos `gain_vs_manual_*` seguem a mesma convenção: valor positivo = redução.

**Condições iguais para as três:** mesmo grafo, mesmos pedidos e entregadores, mesmo A* (validado contra o Dijkstra) e mesmo peso. Cada estratégia roda num grafo com cache vazio, e a ordem de execução não muda o resultado (há teste para isso).

## 1. Dataset oficial (seed 42: 20 pedidos, 4 entregadores)

### Peso distância (padrão)

| Estratégia | km | min | R$ | ETA médio (min) | Maior rota (min) | Desvio de carga | km vs manual | min vs manual | R$ vs manual |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Manual | 176,71 | 371,3 | 59,60 | 45,4 | 105,5 | 0,00 | referência | referência | referência |
| Vizinho mais próximo | 73,02 | 153,4 | 23,86 | 15,7 | 47,7 | 0,00 | redução de 58,7% | redução de 58,7% | redução de 60,0% |
| K-Means + A* | 73,22 | 160,0 | 19,73 | 15,6 | 78,8 | 2,00 | redução de 58,6% | redução de 56,9% | redução de 66,9% |

K-Means + A* em relação ao vizinho mais próximo: aumento de 0,3% em km, aumento de 4,3% em tempo, aumento de 65,1% na maior rota e redução de 17,3% em custo.

| Critério | 1º | 2º | 3º |
| --- | --- | --- | --- |
| Menor distância | Vizinho mais próximo | K-Means + A* | Manual |
| Menor tempo | Vizinho mais próximo | K-Means + A* | Manual |
| Menor custo | K-Means + A* | Vizinho mais próximo | Manual |
| Melhor balanceamento (pedidos) | Manual e vizinho (empate em 0,00) | — | K-Means + A* |

### Peso tempo (`--weight time_min`)

| Estratégia | km | min | Maior rota (min) | R$ |
| --- | ---: | ---: | ---: | ---: |
| Manual | 181,29 | 358,3 | 102,3 | 61,40 |
| Vizinho mais próximo | 68,84 | 137,1 | 42,6 | 23,14 |
| K-Means + A* | 75,64 | 155,1 | 75,6 | 20,66 |

### Leitura

1. **Otimizar vale muito.** As duas estratégias otimizadas têm redução de cerca de 58% no km e no tempo em relação à rota manual. O ETA médio por pedido cai de 45,4 para cerca de 15,7 min, ou seja, o cliente recebe em média 30 minutos antes. A rota manual divide os pedidos por ordem de chegada, e cada entregador atravessa a cidade várias vezes (`routes_manual.png`).
2. **Neste dataset, o K-Means + A* não supera o vizinho mais próximo.** Em relação a ele, tem aumento de 0,3% em km (empate prático), aumento de 4,3% em tempo e aumento de 65,1% na maior rota (78,8 contra 47,7 min). Com peso tempo, a diferença cresce: 155,1 contra 137,1 min.
3. **A causa é a malha viária: ver o caso da zona 0 (seção 2).**
4. **O K-Means + A* é o mais barato em R$** (19,73) por causa da atribuição húngara, e não por percorrer menos (seção 4).
5. **Balanceamento:** o vizinho mais próximo usa cotas fixas (5 pedidos cada, desvio 0). O K-Means aceita zonas de 3 a 7 pedidos (desvio 2,0) para mantê-las compactas. Pedidos iguais não significam trabalho igual: no vizinho mais próximo, a duração das rotas vai de 23 a 48 min (`route_load.png`).
6. **Tempo de cálculo:** milissegundos para as três (manual ≈ 2 ms, vizinho ≈ 6 ms, K-Means + A* ≈ 8–20 ms).

## 2. A limitação do K-Means: o caso da zona 0

**O K-Means agrupa por proximidade em linha reta e não conhece a malha viária.** O dataset oficial mostra isso na prática:

| Zona | Pedidos | Do depósito ao pedido mais próximo, em linha reta | Pelas ruas (A*) | Ruas ÷ linha reta | km da rota |
| --- | ---: | ---: | ---: | ---: | ---: |
| **0 (oeste)** | 7 | **1,5 km** | **6,6 km** | **4,3×** | **35,3** |
| 1 (sudoeste) | 7 | 2,1 km | 3,3 km | 1,6× | 14,2 |
| 2 (norte) | 3 | 1,3 km | 2,7 km | 2,2× | 13,5 |
| 3 (sudeste) | 3 | 0,6 km | 0,9 km | 1,4× | 10,3 |

- **No mapa, a zona 0 parece perto:** o pedido mais próximo fica a 1,5 km do depósito em linha reta.
- **Pelas ruas, ela é distante:** não há rua ligando o depósito diretamente ao oeste (ver `graph_map.png`: o depósito só se liga a N17, N08 e N24). O entregador dá a volta, e o acesso real é 4,3 vezes a linha reta.
- **O resultado** é a rota mais longa do dia, com 35,3 km e 78,8 min.
- **Por que o K-Means não evita isso:** ele vê 7 pedidos compactos e "perto" do depósito e forma a zona. O A* calcula o caminho real, mas só depois que a zona já foi formada. Nada no pipeline volta para corrigir a composição da zona.

## 3. Robustez: 30 datasets sintéticos (seeds 1 a 30)

Um único dataset pode favorecer uma estratégia por acaso. O `benchmark` gera 30 cidades e conjuntos de pedidos diferentes, todos sintéticos, e roda as três estratégias em cada um.

| Estratégia (média) | km | min | R$ | ETA médio (min) | Maior rota (min) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Manual | 126,25 | 289,3 | 47,95 | 36,9 | 94,4 |
| Vizinho mais próximo | 69,09 | 157,1 | 22,65 | 16,2 | 65,5 |
| K-Means + A* | 64,67 | 147,6 | 21,30 | 15,0 | 55,5 |

- Em relação ao vizinho mais próximo, o K-Means + A* tem **redução de 6,4% em km** e **redução de 15,2% na maior rota**.
- Ele percorre menos km em **22 de 30** datasets e tem a maior rota mais curta em **24 de 30**.
- Com peso tempo: 145,3 contra 153,8 min no total, maior rota de 54,6 contra 65,7 min, menos km em 22 de 30.

**Atenção:** são dados sintéticos. As cidades são geradas pelo mesmo gerador (pontos aleatórios, ruas por árvore geradora mínima + ligações curtas). A média mostra a tendência nesse tipo de cenário, não garante o resultado numa cidade real.

## 4. Atribuição húngara: reduz custo, não km nem tempo

O algoritmo húngaro escolhe qual entregador fica com cada zona, minimizando `km da zona × custo/km`. No dataset, ele dá a zona 0 (35,3 km) à bike (R$ 0,10/km).

- **Reduz o custo em R$:** a mesma distância fica mais barata quando é percorrida pelo veículo de menor custo por km.
- **Não muda o km nem o tempo:** os km de cada zona não dependem de quem a percorre. No modelo, todos os veículos andam na mesma velocidade e saem do mesmo depósito. Trocar os entregadores entre as zonas mantém o total de km e de minutos.
- **Ressalva:** na vida real, a bike é mais lenta. Dar a ela a zona mais longa pioraria o tempo. Isso é uma limitação do modelo, não uma vantagem real.

## 5. Quando o K-Means + A* é melhor ou pior

| Situação | Quem tende a ganhar | Por quê |
| --- | --- | --- |
| Pedidos em grupos bem separados | K-Means + A* | Cada entregador fica numa região e não cruza a cidade |
| Malha com "barreiras" (sem ligação direta entre regiões vizinhas) | Vizinho mais próximo | Ele escolhe pelo custo real do A*; o K-Means agrupa por linha reta |
| Zona compacta, mas de acesso difícil a partir do depósito | Vizinho mais próximo | O K-Means não considera o depósito (caso da zona 0) |
| Objetivo: terminar todas as entregas cedo (maior rota) | K-Means + A*, em média | O vizinho deixa os últimos entregadores com o que sobrou, espalhado |
| Objetivo: mesmo número de pedidos por entregador | Vizinho mais próximo | Usa cotas fixas; o K-Means aceita zonas desiguais |

**Conclusão:** nos 30 cenários sintéticos, o K-Means + A* é a melhor estratégia **em média** (menos km, menor maior rota, menor ETA). Não vence em todos os cenários: no dataset oficial, perde para o vizinho mais próximo por causa da malha viária, exatamente a limitação conhecida do K-Means. As duas estratégias otimizadas superam a rota manual em todos os 30 cenários: a menor redução de km observada foi de 32,7% (vizinho mais próximo) e 26,5% (K-Means + A*).

## 6. Escolha de k

| k | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Inércia (km²) | 58,5 | 29,2 | 18,0 | 12,9 | 9,6 | 6,3 | 4,2 |
| Silhueta | 0,38 | 0,46 | 0,52 | 0,52 | 0,53 | 0,51 | 0,52 |

A inércia cai bastante até k = 4 e pouco depois: o cotovelo fica em 4. A silhueta de k = 4 (0,52) é quase igual à melhor (0,53, k = 6). Assim, k = 4, o número de entregadores, também é uma boa escolha geométrica. Mas é geométrica: não considera as ruas.

## 7. 2-opt

O 2-opt nunca piorou uma rota (garantido pelo código e testado). No dataset oficial, não encontrou melhoria, porque as zonas têm de 3 a 7 pedidos e a ordem inicial já não tinha cruzamentos. Nos 30 datasets, melhorou 33 de 120 zonas, com redução de 1,4% do km dessas rotas. O efeito deve crescer com mais pedidos por zona.

## 8. Limitações

- **O K-Means não conhece a malha viária nem o depósito** (seção 2).
- O balanceamento limita só o tamanho máximo e conta pedidos, não minutos.
- Velocidades fixas por rua, sem trânsito; o veículo não muda a velocidade.
- Sem capacidade, prioridade ou janela de horário.
- Grafo sintético de 40 nós; os resultados absolutos não representam São Paulo real.

## 9. Melhorias sugeridas

1. **Agrupar pela distância de rua:** K-Medoids sobre a matriz de custos A*. Ataca diretamente o caso da zona 0.
2. **Considerar o depósito:** método *sweep* (ângulo a partir do depósito) ou distância ao depósito como atributo.
3. **Trocas de pedidos entre zonas** depois do roteamento, balanceando pela duração.
4. **Escolher k pelo custo total**, testando k = 2 até o número de entregadores.
5. **Restrições reais:** capacidade, janelas de horário e velocidade por veículo (VRP).
6. **Dados reais:** malha do OpenStreetMap e velocidades por horário de pico.
