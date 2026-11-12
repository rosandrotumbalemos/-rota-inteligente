# Roteiro do vídeo pitch (até 4 minutos)

Duração planejada: **3 min 55 s**, com 5 s de folga. As falas somam cerca de 490 palavras, ritmo de uma apresentação calma (~130 palavras por minuto). Os números falados são os do dataset oficial e do benchmark de 30 datasets (`docs/results.md`).

## Antes de gravar

1. Abra o repositório no GitHub Codespaces (ou em um terminal com o projeto instalado) e rode uma vez `python -m rota_core report`, para os arquivos de `outputs/` estarem atualizados.
2. Deixe abertos, em abas: `outputs/maps/graph_map.png`, `outputs/maps/comparison_map.png`, `outputs/maps/zones_map.png`, `outputs/charts/distance_comparison.png` e `outputs/charts/route_load.png`.
3. Aumente a fonte do terminal (16–18 pt) e limpe a tela (`clear`).
4. Grave em 1080p. Publique no YouTube como "não listado" e cole o link no README.

## Resumo

| # | Bloco | Tempo | Tela principal |
| --- | --- | --- | --- |
| 1 | Problema | 0:00–0:25 | Título + `routes_manual.png` |
| 2 | Solução | 0:25–0:50 | `graph_map.png` |
| 3 | Algoritmos | 0:50–1:50 | `zones_map.png` → `routes_kmeans_astar.png` |
| 4 | Demonstração | 1:50–2:40 | Terminal: `run --strategy all` |
| 5 | Resultados | 2:40–3:20 | `comparison_map.png` + `distance_comparison.png` |
| 6 | Limitações | 3:20–3:40 | `zones_map.png` + `graph_map.png` (zona 0) |
| 7 | Conclusão | 3:40–3:55 | README no GitHub |

---

## 1. Problema (0:00–0:25)

**Tela:** slide de título "Rota Inteligente — Sabor Express", depois `outputs/maps/routes_manual.png`.

**Fala:**
> A Sabor Express é um delivery fictício do centro de São Paulo. No horário de pico, os pedidos são divididos pela ordem de chegada e cada entregador decide o caminho pela experiência. O resultado está neste mapa: rotas que cruzam a cidade, 177 quilômetros para 20 pedidos e clientes esperando 45 minutos em média.

## 2. Solução (0:25–0:50)

**Tela:** `outputs/maps/graph_map.png`.

**Fala:**
> A solução trata a cidade como um grafo. São 40 nós, que representam a cozinha e os bairros, e 60 ruas, cada uma com distância e tempo. Cada pedido é ligado ao nó mais próximo. A partir daí, o sistema decide quais pedidos vão juntos, em que ordem e por qual caminho, tudo em Python e sem nenhuma API paga.

## 3. Algoritmos (0:50–1:50)

**Tela:** `outputs/maps/zones_map.png` (0:50–1:20), depois `outputs/maps/routes_kmeans_astar.png` (1:20–1:50).

**Fala:**
> A estratégia principal tem quatro peças. Primeiro, o K-Means agrupa os pedidos em quatro zonas, uma por entregador, e um balanceamento impede que uma zona fique grande demais. Depois, o algoritmo húngaro decide qual entregador fica com cada zona, pelo menor custo por quilômetro.
>
> Dentro de cada zona, a ordem de visita começa pelo vizinho mais próximo e é melhorada com o 2-opt, que desfaz cruzamentos e só aceita mudanças que reduzem o percurso. Por fim, cada trecho é calculado com o A estrela. A heurística é a distância em linha reta, que nunca é maior que o caminho real, e por isso o caminho encontrado é o melhor possível. Validamos o A estrela contra o Dijkstra em 250 pares de pontos.

## 4. Demonstração (1:50–2:40)

**Tela:** terminal.

**Comandos:**

```bash
python -m rota_core validate-data
python -m rota_core run --strategy all
```

Role até a tabela "Comparação" e, se der tempo, mostre que `python -m rota_core report` gera os mapas, gráficos e o `report.md`.

**Fala:**
> Na prática, tudo roda pela linha de comando. O primeiro comando valida os dados: 40 nós, 60 ruas, 20 pedidos e 4 entregadores. O segundo executa as três estratégias: a rota manual, o vizinho mais próximo e o K-Means com A estrela. Para cada entregador aparecem os pedidos, os quilômetros, os minutos e o custo, e no final, a comparação. Cada estratégia leva poucos milissegundos. O comando report gera os mapas, os gráficos e um relatório completo. O projeto tem 172 testes automatizados.

## 5. Resultados (2:40–3:20)

**Tela:** `outputs/maps/comparison_map.png` (2:40–3:00), depois `outputs/charts/distance_comparison.png`.

**Fala:**
> Otimizar faz muita diferença. Em relação à rota manual, as duas estratégias otimizadas têm redução de cerca de 58% nos quilômetros, e o tempo médio até o cliente cai de 45 para 16 minutos. Entre elas, sendo honesto: neste dataset, o K-Means empata com o vizinho mais próximo em distância e tem a rota mais longa. Por isso testamos 30 cenários sintéticos. Na média, o K-Means com A estrela tem redução de 6% nos quilômetros e de 15% na rota mais longa, e vence em 22 dos 30.

## 6. Limitações (3:20–3:40)

**Tela:** `outputs/maps/zones_map.png`, com destaque para a zona 0 (oeste). Se possível, mostre ao lado `outputs/maps/graph_map.png`, onde se vê que o depósito só se liga a três ruas.

**Fala:**
> E por que ele perde aqui? Por causa desta zona. Em linha reta, ela fica a um quilômetro e meio da cozinha; pelas ruas, a seis e meio. O K-Means agrupa por linha reta e não enxerga a malha viária. Os dados também são sintéticos, sem trânsito real.

## 7. Conclusão (3:40–3:55)

**Tela:** README no GitHub, rolando até "Resultados visuais".

**Fala:**
> A inteligência artificial clássica reduz mais da metade dos quilômetros, e os testes mostram onde cada estratégia funciona melhor. Próximo passo: agrupar pela distância real das ruas. Código, dados e resultados estão no GitHub. Obrigado.

---

## Dicas

- **Se passar de 4 minutos,** encurte a demonstração (bloco 4): mostre só a tabela de comparação.
- **Nos números,** fale "cerca de" e arredonde (58%, 16 minutos, 6%). Os valores exatos estão no README.
- **Não diga** que o K-Means "sempre" ganha: ele vence em média, não em todos os casos.
