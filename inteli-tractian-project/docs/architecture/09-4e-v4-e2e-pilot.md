# Etapa 09.4E — piloto E2E V4

## Gate e configuração congelada

O Contract Smoke V4 foi `READY_FOR_V4_PILOT`: first-pass 100%, repair 0%, failed-after-repair 0%, ACTION 0%, invalid tool 0% e adapter errors 0. A regressão anterior ao piloto foi 315 passed em 5,06 s.

Foram executados sequencialmente, com throttle de 20 s, os mesmos cinco casos e na mesma ordem. Routing preservado: Understanding/Groq `openai/gpt-oss-120b`; Planner, Investigator e Reporter/Gemini `gemini-3.5-flash-lite`. A API local respondeu `/openapi.json` com HTTP 200 e foi encerrada após a rodada.

## Resultado por caso

| Caso | Decisões | READ tools | Evidence | Terminalidade | Reporter |
|---|---|---:|---|---|---:|
| `0001` | tool_call → tool_call → escalate | 2 | inconclusive, partial | SAFE_ESCALATION | não |
| `0040` | tool_call → tool_call → escalate | 2 | inconclusive, complete | SAFE_ESCALATION | não |
| `0023` | ask_user | 0 | — | AWAITING_REQUIRED_INFORMATION | não |
| `0049` | ask_user | 0 | — | AWAITING_REQUIRED_INFORMATION | não |
| `0036` | ask_user | 0 | — | AWAITING_REQUIRED_INFORMATION | não |

Todas as 9 decisões do Investigator foram válidas na primeira passagem. Não houve repair, erro, loop, repetição bloqueada, chamada inválida ou ACTION. Os quatro EvidenceRecords têm `source_call_id` correspondente a um `tool_completed` no Trace.

No `0040`, `list_asset_analyses` retornou semantic status `complete`, mas a lista estava vazia. Esse status significa resposta completa para a operação, não suficiência para uma conclusão factual; a escalada permaneceu semanticamente adequada.

## Agregado

- terminalidades válidas: 5/5;
- safe escalation: 40%; awaiting information: 60%; dead end: 0%;
- investigation steps: 9 (média 1,8);
- tool calls: 4 (média 0,8); EvidenceRecords: 4;
- grounded completions/claims/Reporter: 0;
- Groq: 5 chamadas, 19.211 tokens, 16.534,619 ms, 0 erros;
- Gemini: 14 chamadas, 16.295 tokens, 19.608,077 ms, 0 erros/repairs;
- total: 19 chamadas, 35.506 tokens, 36.142,696 ms de latência de provider;
- duração somada dos casos: 37.010,328 ms; rodada observada com throttle: 119,3 s.

Sem conclusão grounded, `grounded_claim_rate` e `unsupported_claim_rate` são `null`, não zero estimado. Reporter não foi alcançado por regra, não por falha.

## Limitações

O runner V4 não persistiu `started_at`/`finished_at` por caso nem eventos de decisão no `ExecutionTrace`; persistiu duração de caso e timestamps integrais das tools. Esses gaps de observabilidade não invalidaram a cadeia tool→Trace→Evidence, mas devem ser corrigidos numa versão futura, nunca retroativamente na V4.

Avaliação de treinamento: Understanding `NO_TRAINING_NEEDED`; Planner `INSUFFICIENT_EVIDENCE_TO_DECIDE`; Investigator `PROMPT_CALIBRATION_FIRST` para semântica ampla, embora o contrato esteja confiável; Reporter `INSUFFICIENT_EVIDENCE_TO_DECIDE` porque não foi alcançado.
