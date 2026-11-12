# Arquitetura

Três blocos com dependência num só sentido: **frontend → API → núcleo de IA**.

```text
[PWA Next.js]  --HTTP/JSON-->  [API FastAPI]  --chamada Python-->  [rota_core]
                                     |
                                     v
                               [PostgreSQL]
```

## Núcleo de IA (`core/rota_core`)

| Camada | Responsabilidade | Estado |
| --- | --- | --- |
| `data/` | Ler e validar CSVs; gerar dados fictícios com seed | Pronto (Etapa 1) |
| `domain/` | Modelos Pydantic: Node, Edge, Order, Courier, Route, RouteStop, OptimizationRun, Metrics | Pronto (Etapa 1) |
| `graph/` | Grafo NetworkX dirigido; Haversine | Pronto (Etapa 1) |
| `algorithms/` | A*, snap, matriz de custos com cache, rota manual, vizinho mais próximo, K-Means + balanceamento, 2-opt, atribuição húngara e a estratégia K-Means + A* | Pronto (Etapas 3–5) |
| `services/` | `optimizer` (executa e cronometra as estratégias), `metrics` (métricas e comparação), `benchmark` (robustez) | Pronto |
| `reporting/` | `maps`, `charts`, `report` e `style` (paleta validada para daltonismo) | Pronto |
| `cli.py` | `generate-data`, `validate-data`, `run [--report]`, `report`, `benchmark` | Pronto |

Regra: o núcleo não importa FastAPI, SQLAlchemy nem nada de banco. A API converte seus modelos em modelos de domínio num único adaptador.

## API e frontend

Ver `backend/README.md` e `frontend/README.md`. Contratos, modelo de dados e Docker Compose estão no plano técnico aprovado.
