# Etapa 09.7B — Full DEV V2: execução e estado final

## Preflight

| Portão | Resultado |
|---|---|
| §1 commit / árvore | `4a2de75`, limpa, manifesto V2 íntegro, 60 casos no split |
| §2 regressão offline | 407 passed (subiu a 419 com as correções desta etapa) |
| §3 sonda mínima Groq | sucesso, 388 ms |
| §3 gate representativo | `QUOTA_AVAILABLE`, schema válido, 3.790 ms |

## Execução

A retomada exigiu três passadas. As duas primeiras morreram por defeitos meus no runner, ambos corrigidos com teste de regressão; nenhuma perdeu dado medido.

| Passada | Desfecho |
|---|---|
| 1ª | interrompida por mim: 41% dos casos morriam em HTTP 503 do Gemini, queimando cota do Groq em trabalho descartável |
| 2ª | `NameError` — rename deixou `quota_blocked` órfão no `main` |
| 3ª | `ValidationError` no caso 30 — relógio do sistema voltou 2h20 e produziu duração negativa |
| 4ª | avançou até esgotar a cota diária do Groq |

Estado final da janela:

| Medida | Valor |
|---|---:|
| Medidos comportamentalmente | **33 / 60 (55%)** |
| Falhas do agente | **0** |
| Bloqueados por infraestrutura | 17 |
| Nunca tentados | 10 |
| Tokens Groq consumidos no dia | 200.683 |

As 17 exclusões são 13 `PROVIDER_ERROR` (HTTP 503 do Gemini), 3 `RATE_LIMIT` e 1 `TIMEOUT`. Nenhuma é decisão do agente, e todas voltam à fila na próxima janela.

## Resultado dos 33 casos medidos

Terminalidade válida **100%**, sem dead end, sem falha comportamental, sem ACTION.

| Terminalidade | Casos |
|---|---:|
| `AWAITING_REQUIRED_INFORMATION` | 17 |
| `SAFE_ESCALATION` | 16 |
| `GROUNDED_COMPLETION` | 0 |

Custo: 145 chamadas LLM, 410.980 tokens, 1,39 tool calls por caso. P50 42.769 ms, P95 125.814 ms — latência alta por degradação do Gemini, que também produziu os 503.

Evidência: 46 EvidenceRecords, **0 órfãos**. Estados semânticos: 20 `complete`, 13 `inconclusive`, 6 `partial`, 4 `conflict`, 3 `unavailable`.

## Correções desta etapa

**Retry com backoff.** O Gemini devolvia HTTP 503 e o retry acontecia no mesmo instante. `RetryPolicy` passou a declarar espera exponencial (2 s, depois 4 s) com `sleeper` injetável para teste. A mortalidade por provider caiu de 7 em 17 casos para 2 em 12 logo após a ativação.

**Falha de provider fora da população comportamental.** `e2e_metrics` passou a expor `behavioral_failure_rate`, `provider_failure_count` e `valid_terminal_state_rate_excluding_provider`. A regra é estrita: só é absolvido o caso cujos erros são **todos** da camada `PROVIDER`; qualquer causa mista continua comportamental.

**Retomada de casos mortos por infraestrutura.** Antes só `RATE_LIMIT` voltava à fila; 503 e timeout ficavam marcados como concluídos e seriam pulados para sempre, apesar de nunca terem sido medidos.

**Duração por relógio monotônico.** `run_case` media duração subtraindo duas leituras de `datetime.now()`. O relógio de parede da máquina andou para trás 2h20 e gerou `duration_ms = -8438990`, derrubando o runner. Agora o decorrido vem de `perf_counter()` e `finished_at` é derivado da âncora, preservando o invariante do `RunTiming`.

**Teste que executa, não que lê.** O `NameError` passou por 416 testes verdes porque o teste do resume inspecionava o *texto* de `main` com `inspect.getsource`. Foi adicionado um teste que executa `main` no caminho sem `--execute`, com API e auditoria substituídas por fakes.

## Cobertura de dados

Inalterada, como esperado — dataset e API não foram tocados: 0 totalmente alinhados, 24 parciais, 26 desalinhados, 10 sem entidade resolvível, 52 com pedido temporal sem suporte.

## Quality gates

| Dimensão | Veredicto | Interpretável a 55%? |
|---|---|---|
| ARCHITECTURE_STABILITY | PASS | parcial |
| CONTRACT_RELIABILITY | PASS | parcial |
| INVESTIGATION_QUALITY | FAIL | parcial |
| GROUNDING_QUALITY | PASS_WITH_WARNINGS | não exercitado |
| REPORTER_QUALITY | PASS_WITH_WARNINGS | não alcançado |
| DATA_COVERAGE | **FAIL** | **sim** — auditoria dos 60 |
| PROVIDER_STABILITY | PASS | parcial |

O piso `MINIMUM_SPLIT_COVERAGE = 0,80` mantém os quatro componentes em `INSUFFICIENT_EVIDENCE_TO_DECIDE`. Com 55% do split, nenhum veredicto de treinamento é declarado.

## Retomada

```
python -m scripts.run_full_dev_evaluation --execute --throttle-seconds 25
```

Preserva os 33 medidos e reexecuta os 27 restantes — 17 bloqueados por infraestrutura e 10 nunca tentados. Faltam ~110 mil tokens de Groq, o que exige a próxima janela diária.

## Status

`RUN_PAUSED_PROVIDER_QUOTA`.
