# Etapa 09.7 — Full DEV V2: execução parcial

## Preflight

Todos os portões anteriores à execução foram aprovados.

| Portão | Resultado |
|---|---|
| §1 commit / árvore limpa | `ee92af2`, sem alteração de produção pendente |
| §2 regressão offline | 405 passed, 0 failed, 0 skipped, 1 warning conhecido |
| §3 conectividade Groq | sucesso, 434 ms |
| §3 conectividade Gemini | sucesso, 50.562 ms (latência anômala, registrada) |
| §4 gate de cota do Groq | `QUOTA_AVAILABLE` — uma chamada, schema válido, 3.873 tokens |
| §9 guard de leakage | 5 testes estruturais novos |

O guard do §9 não depende de disciplina: inspeciona o código de `run_case` e prova que a amostra só é acessada por `sample_id`, `training_tags` e `runtime_payload(sample)`; que nenhum contrato de runtime declara campo `target`; que `extra="forbid"` recusa a amostra inteira; e que `sample.target` só aparece em `understanding_metrics`, executado depois de todos os casos.

## Configuração congelada

`e2e-full-dev-v2` / `MODEL_ROUTING_V5`. Atribuição de routing inalterada — o incremento de versão reflete mudanças de configuração, prompt e capability.

| Item | Valor |
|---|---|
| Understanding | Groq `openai/gpt-oss-120b`, `understanding_prompt_v2`, 2048 tokens |
| Planner / Investigator / Reporter | Gemini `gemini-3.5-flash-lite` |
| Orçamentos de saída | 1200 / 900 / 1600 |
| Teto do provider Gemini | 8192 (era 512) |
| Completion Policy | `completion_policy_v1_09_4C`, inalterada |
| Política temporal | `temporal_policy_v1_09_6` |
| Limites | 12 passos, 8 tool calls, `temperature=0` |
| Throttle | 25 s (V1 usou 20 s) |
| Retry Gemini | 2 tentativas |

Os 60 `sample_id` são exatamente os da V1. Nenhum caso difícil foi removido.

## Interrupção por cota

A rodada parou após 3 casos medidos, com `RUN_PAUSED_PROVIDER_QUOTA`.

| Medida | Valor |
|---|---:|
| Casos medidos | 3 de 60 (5%) |
| Casos derrubados por cota | 3 |
| Casos pendentes | 57 |
| Tokens Groq consumidos na janela | 12.134 |

Caracterização do limite, feita com duas sondas e sem tentativas repetidas: chamada de 16 tokens **passa** (403 ms); chamada completa de Understanding recebe **HTTP 429** em 96 ms. Como o espaçamento de 25 s manteria qualquer teto por minuto sob controle, o limite ligante é o **orçamento diário de tokens** do free tier, praticamente exaurido — três chamadas de ~4 mil tokens consumiram o saldo restante.

Nenhum provider foi trocado automaticamente. Casos derrubados por cota voltaram à fila de pendentes e **não contam como falha do sistema**: contá-los como `FAILED` atribuiria ao agente um problema do provider, e a agregação passou a separá-los explicitamente.

## O que os 3 casos medidos mostram

Comparação pareada contra os mesmos casos na V1.

| Caso | Terminal V1 | Terminal V2 | Classe V1 | Classe V2 |
|---|---|---|---|---|
| `0001` | SAFE_ESCALATION | SAFE_ESCALATION | contextualize | contextualize |
| `0002` | SAFE_ESCALATION | SAFE_ESCALATION | contextualize | contextualize |
| `0003` | SAFE_ESCALATION | SAFE_ESCALATION | contextualize | contextualize |

Indicadores da amostra medida:

- terminalidade válida 3/3, dead ends 0, falhas 0;
- Planner 3/3 com `finish=STOP` e schema válido; **0 truncamentos**;
- Investigator 9 decisões, **100% válidas em primeira passagem**, 0 repairs, 0 argumentos inválidos, **0 argumentos temporais inventados**;
- política temporal acionada em 3/3 com `TEMPORAL_FILTER_UNSUPPORTED` → `PROCEED_WITHOUT_FILTER`;
- 6 EvidenceRecords, **0 órfãos**; estados semânticos `complete` 2, `inconclusive` 2, `partial` 1, `conflict` 1;
- Trace completo por caso: understanding, planner, decisão produzida, validada, aceita, tool requested/started/completed, evidence created, terminal state;
- ACTION 0; erros de provider entre os casos medidos: 0.

Latência subiu de forma relevante: P50 44.677 ms contra 7.469 ms na V1, com o Gemini respondendo lentamente também na sonda de conectividade. Não é conclusivo com n=3.

## Limite de leitura

**Três casos não sustentam as decisões dos §24 a §29.** Todos os três são `contextualize` e já eram acertados na V1, então não exercitam justamente o que a Etapa 09.6 corrigiu: nenhum caso `execute`, nenhum dos quatro Planners que truncavam, nenhum pedido temporal que levasse a `ASK_USER`.

O que os 3 casos sustentam é ausência de regressão estrutural: mesma terminalidade, mesma classe, contrato íntegro, evidência sem órfãos.

## Quality gates

Calculados sobre os 3 casos medidos e sobre a auditoria de cobertura, que cobre os 60.

| Dimensão | Veredicto | Interpretável? |
|---|---|---|
| ARCHITECTURE_STABILITY | PASS | não — 3 casos |
| CONTRACT_RELIABILITY | PASS | não — 9 decisões |
| INVESTIGATION_QUALITY | FAIL | não — 3 casos |
| GROUNDING_QUALITY | PASS_WITH_WARNINGS | não exercitado |
| REPORTER_QUALITY | PASS_WITH_WARNINGS | não alcançado |
| DATA_COVERAGE | **FAIL** | **sim** — auditoria determinística dos 60 |
| PROVIDER_STABILITY | PASS | não — 15 chamadas |

`DATA_COVERAGE` é o único veredicto que se sustenta: a auditoria não depende da execução e roda sobre o split inteiro.

Os quatro componentes recebem `INSUFFICIENT_EVIDENCE_TO_DECIDE`, por um piso de cobertura de 80% introduzido nesta etapa após o assessment automático ter declarado o Understanding `NO_TRAINING_NEEDED` a partir de três casos fáceis.

## Retomada

```
python -m scripts.run_full_dev_evaluation --execute --throttle-seconds 25
```

Retoma de `runs.jsonl`, pula os 3 medidos e refaz os 3 derrubados por cota. Cada caso mantém `run_id`, `started_at`, `finished_at`, `duration_ms` e status próprios.

## Status

`RUN_PAUSED_PROVIDER_QUOTA`.
