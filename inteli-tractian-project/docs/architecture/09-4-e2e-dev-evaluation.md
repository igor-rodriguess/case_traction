# 09.4 — End-to-End Synthetic DEV Evaluation

## Configuração congelada

O experimento usa `MODEL_ROUTING_V1` sem fallback automático:

| Componente | Provider | Modelo |
| --- | --- | --- |
| Understanding | Groq | ID configurado em `GROQ_MODEL`/`GROQ_INVESTIGATOR_MODEL` |
| Planner | Gemini | ID configurado em `GEMINI_MODEL`/`GEMINI_UNDERSTANDING_MODEL` |
| Investigator | Gemini | mesmo ID Gemini congelado para a rodada |
| Reporter | Gemini | mesmo ID Gemini congelado para a rodada |

O manifest do experimento registra os IDs reais lidos no ambiente no momento da execução. Nenhum segredo é persistido.

## Limites e isolamento

O runner [run_e2e_dev_pilot.py](../../api/scripts/run_e2e_dev_pilot.py) usa somente `load_dev_split()`. TRAIN, HOLDOUT e Golden Set não são abertos. ACTIONs não pertencem ao registry do Investigator; somente as dez READ tools aprovadas podem atravessar o executor rastreado.

Os limites canônicos de `InvestigationState` permanecem inalterados: `max_investigation_steps=12` e `max_tool_calls=8`.

## Fase A

O runner seleciona determinística e sequencialmente cinco casos DEV, buscando as tags disponíveis `easy`, `multi_asset`, `ambiguity_present`, `mixed_or_unclear` e `execute_or_handoff_recognition`. Para cada execução ele persiste em `experiments/e2e-dev-v1/`:

- `manifest.json`;
- `runs.jsonl`;
- `component-metrics.jsonl`;
- `aggregate-metrics.json`;
- `errors.jsonl`;
- `showcase.json`.

Cada caso preserva outputs estruturados por componente, decisões, Trace, Evidence Ledger, modelos/providers, uso, latência e erros sanitizados. Não há chain-of-thought.

## Resultado da Fase A — 2026-09-04

Foram executados sequencialmente os cinco IDs congelados: `syn_u_dev_0001`, `syn_u_dev_0040`, `syn_u_dev_0023`, `syn_u_dev_0049` e `syn_u_dev_0036`. A API local respondeu ao pre-flight, e Groq/Gemini tiveram conectividade confirmada antes da rodada.

| Sample | Resultado observado | Classificação |
| --- | --- | --- |
| `syn_u_dev_0001` | Understanding Groq e Planner Gemini válidos; saída do Investigator não atravessou a fronteira de contrato | `FAILED` |
| `syn_u_dev_0040` | Understanding Groq retornou saída inválida/truncada (`finish_reason=length`) | `FAILED` |
| `syn_u_dev_0023` | Groq retornou `rate_limit` no Understanding | `FAILED` |
| `syn_u_dev_0049` | Groq retornou `rate_limit` no Understanding | `FAILED` |
| `syn_u_dev_0036` | Groq retornou `rate_limit` no Understanding | `FAILED` |

Foram feitas seis chamadas LLM: cinco ao Groq e uma ao Gemini. Nenhuma tool foi executada, portanto o Trace e o Evidence Ledger ficaram vazios, nenhuma claim/conclusão foi criada e nenhum ReporterOutput foi produzido. Não houve 429 reportado no artefato normalizado; os três casos são registrados pelo adapter como `rate_limit` e requerem diagnóstico posterior do HTTP/provider antes de qualquer novo experimento.

Os artefatos reais estão em `experiments/e2e-dev-v1/`. O showcase contém as cinco execuções e não inventa resultados ausentes.

## Regressão pós-piloto

`285 passed`, `0 failed`, `0 skipped`, `1 warning` conhecido de depreciação do Starlette. A suíte não fez chamadas externas.

## Estado atual

`BLOCKED_EXECUTION`: o piloto demonstrou que `MODEL_ROUTING_V1` não é estável o suficiente para avançar ao DEV completo. Não houve alteração de prompt, modelo, routing, schema, tool surface ou limites durante a rodada.

Golden Set acessado: **NÃO**. TRAIN acessado: **NÃO**. HOLDOUT acessado: **NÃO**. ACTION executada: **NÃO**. Segredos persistidos: **NÃO**.
