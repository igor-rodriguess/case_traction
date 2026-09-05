# Etapa 09.7 — Comparação V1 × V2

## Base da comparação

A V1 tem 60 casos medidos. A V2 tem **3**. Comparar agregados de populações tão diferentes produziria número sem significado, então tudo aqui é **pareado caso a caso** ou explicitamente marcado como não medido.

| Origem | Casos medidos | Cobertura do split |
|---|---:|---:|
| Full DEV V1 | 60 | 100% |
| Full DEV V2 | 3 | 5% |

## Understanding

Nos 3 casos pareados: classe idêntica em 3/3, todas corretas (`contextualize`), schema válido em 3/3.

Isso **não valida a calibração**. Os três já eram acertados na V1, e a correção do prompt v2 mira a classe `execute`, que não aparece nesta amostra.

A evidência que existe sobre a calibração continua sendo a da Etapa 09.6, medida isoladamente em 30 casos pareados:

| Classe | Suporte | Recall V1 → V2 | Precisão V1 → V2 |
|---|---:|---|---|
| `execute` | 5 | 0,00 → **1,00** | — → 1,00 |
| `unclear` | 2 | 0,00 → **1,00** | — → 0,67 |
| `investigate` | 12 | 1,00 → 1,00 | 0,80 → **1,00** |
| `contextualize` | 10 | 0,90 → 0,90 | 1,00 → 1,00 |
| `mixed` | 1 | 0,00 → 0,00 | 0,00 → 0,00 |

Acurácia 0,70 → 0,93, zero regressões. Medida em Understanding isolado, **não** no fluxo E2E completo.

## Planner e truncamento

| Medida | V1 (60 casos) | V2 (3 casos) |
|---|---:|---:|
| Schema válido | 91,5% | 100% |
| `finish=MAX_TOKENS` | 4 | **0** |
| Teto efetivo do provider | 512 | 8192 |

Os quatro casos que truncavam na V1 — `0025`, `0026`, `0034`, `0051` — **não estão entre os 3 medidos**. A prova do reparo continua sendo a verificação causal da Etapa 09.6, que os reexecutou com o `UnderstandingOutput` gravado e obteve 4/4 com schema válido, um deles consumindo 582 tokens, acima do teto antigo.

## Investigator

| Medida | V1 (117 decisões) | V2 (9 decisões) |
|---|---:|---:|
| Válidas em primeira passagem | 94,0% | 100% |
| Taxa de repair | 6,0% | 0% |
| Falha após repair | 0% | 0% |
| Argumentos inválidos | 6,0% | 0% |
| Argumentos temporais inventados | 3 (`time_window`, `hours`, `window`) | **0** |
| Tool inválida | 0% | 0% |
| ACTION | 0 | 0 |
| Loop | 0% | 0% |

Nove decisões não permitem afirmar que o contrato de capability eliminou os argumentos temporais inventados. Permitem afirmar que nenhum apareceu, e que a política temporal foi acionada em 3/3 com `TEMPORAL_FILTER_UNSUPPORTED` → `PROCEED_WITHOUT_FILTER`.

## Sistema

| Medida | V1 (60) | V2 (3) |
|---|---:|---:|
| Terminalidade válida | 88,3% | 100% |
| Falhas | 7 | 0 |
| Dead ends | 0 | 0 |
| Chamadas LLM | 243 | 15 |
| Tokens | 462.281 | 40.902 |
| Tokens por caso | 7.705 | 13.634 |
| P50 latência | 7.469 ms | 44.677 ms |
| P95 latência | 26.281 ms | 78.224 ms |
| EvidenceRecords órfãos | 0 | 0 |

Tokens por caso subiram porque o `InvestigatorInput` agora carrega os contratos de capability e a orientação temporal. É custo deliberado: substitui suposição de parâmetro por contrato explícito.

A latência triplicou, com o Gemini lento também na sonda de conectividade (50,5 s para 16 tokens). Com n=3 não é possível separar degradação do provider de efeito do payload maior.

## Providers

| Medida | V1 | V2 |
|---|---:|---:|
| Erros entre casos medidos | 1 (5xx, não contabilizado por defeito de gravação) | 0 |
| HTTP 429 durante a rodada | 0 | 3 (interromperam a rodada) |
| Timeouts | 0 | 0 |

Na V1 o 5xx observado não entrava em `provider_error_rate` porque o guard levantava antes de o componente existir. O ledger de chamadas da Etapa 09.6 fechou essa lacuna: na V2 toda chamada é gravada antes do guard decidir.

## Cobertura de dados

Idêntica, como esperado — dataset e API não foram tocados:

| Medida | V1 | V2 |
|---|---:|---:|
| Totalmente alinhados | 0 / 60 | 0 / 60 |
| Parcialmente alinhados | 24 | 24 |
| Desalinhados | 26 | 26 |
| Sem entidade resolvível | 10 | 10 |
| Pedidos temporais sem suporte | 52 | 52 |
| Descritores corroborados | 0 | 0 |

A estabilidade confirma que a auditoria é determinística: mesmos dados, mesmos números.

## O que continua não medido

- terminalidades e taxa de terminal válido sobre os 60;
- efeito da calibração do Understanding no fluxo E2E;
- se os quatro Planners reparados atravessam o pipeline inteiro;
- taxas de `ASK_USER` e `ESCALATE` sob a política temporal em escala;
- se o Reporter é alcançado;
- custo e latência representativos.

## Status

`RUN_PAUSED_PROVIDER_QUOTA`.
