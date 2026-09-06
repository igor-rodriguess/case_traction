# Etapa 09.7B — Comparação pareada V1 × V2

Todos os números abaixo comparam **os mesmos 33 casos** medidos nas duas rodadas. A V1 tem 60 casos e a V2 tem 33; comparar agregados de populações diferentes não diria nada, então a comparação é caso a caso.

## Understanding

A calibração do prompt v2 é confirmada no fluxo E2E completo, não apenas em Understanding isolado.

| Medida | V1 | V2 |
|---|---:|---:|
| Acurácia de `request_class` | 0,848 | **0,970** |

Recall por classe, nos mesmos casos:

| Classe | Suporte | V1 | V2 |
|---|---:|---:|---:|
| `execute` | 4 | **0,00** | **1,00** |
| `investigate` | 21 | 1,00 | 1,00 |
| `contextualize` | 8 | 0,88 | 0,88 |

Matriz de confusão da V2: 21 `investigate` corretos, 7 `contextualize` corretos, 4 `execute` corretos, e um único erro — `contextualize` classificado como `mixed`.

O padrão que a Etapa 09.5 diagnosticou desapareceu: os 4 casos `execute` desta amostra viravam `mixed` na V1 e agora são classificados corretamente. **Zero regressões** nas outras classes.

A precisão de `mixed` não é calculável aqui: a V2 não previu `mixed` para nenhum caso cujo alvo fosse `mixed`, e os 4 casos com alvo `mixed` do split estão entre os 27 ainda não medidos.

## Planner

| Medida | V1 (60) | V2 (33) |
|---|---:|---:|
| Schema válido | 91,5% | **100%** |
| `finish=MAX_TOKENS` | 4 | **0** |
| `output_truncated` | — | **0** |
| Teto efetivo do provider | 512 | 8192 |

Todas as 33 chamadas terminaram com `STOP`. O reparo do teto de tokens se sustenta no fluxo completo.

## Investigator

| Medida | V1 (117 decisões) | V2 (79 decisões) |
|---|---:|---:|
| Válidas em primeira passagem | 94,0% | **100%** |
| Taxa de repair | 6,0% | **0%** |
| Falha após repair | 0% | 0% |
| Argumentos inválidos | 6,0% | **0%** |
| Argumentos temporais inventados | 3 (`time_window`, `hours`, `window`) | **0** |
| Tool inválida | 0% | 0% |
| ACTION | 0 | 0 |

Nenhum campo foi rejeitado por validação na V2. Os `capability_contracts` e a `temporal_guidance` no `InvestigatorInput` removeram a necessidade de o modelo supor parâmetros — que era a origem dos argumentos temporais inventados.

## Sistema, nos mesmos 33 casos

| Terminalidade | V1 | V2 |
|---|---:|---:|
| `SAFE_ESCALATION` | 13 | 16 |
| `AWAITING_REQUIRED_INFORMATION` | 15 | 17 |
| `FAILED` | **5** | **0** |
| `GROUNDED_COMPLETION` | 0 | 0 |

Terminalidade válida **84,8% → 100%**. As 5 falhas da V1 nestes casos eram truncamento do Planner e erro transitório de provider, ambos endereçados.

`GROUNDED_COMPLETION` permanece zero nas duas rodadas — e isso é esperado, não regressão: nenhum dos 60 casos do split é `FULLY_ALIGNED`.

| Medida | V1 (60) | V2 (33) |
|---|---:|---:|
| EvidenceRecords órfãos | 0 | 0 |
| Tool calls por caso | 1,08 | 1,39 |
| Tokens por caso | 7.705 | 12.454 |
| P50 latência | 7.469 ms | 42.769 ms |
| P95 latência | 26.281 ms | 125.814 ms |

Tokens por caso subiram porque o `InvestigatorInput` carrega os contratos de capability — custo deliberado, que troca suposição de parâmetro por contrato explícito. A latência subiu por degradação do Gemini, o mesmo provider que produziu os 13 HTTP 503; não é atribuível às alterações desta etapa.

## Providers

| Medida | V1 | V2 |
|---|---:|---:|
| Erros contabilizados | 1 (subestimado por defeito de gravação) | 17 |
| HTTP 503 | 0 | 13 |
| HTTP 429 | 0 | 3 |
| Timeout | 0 | 1 |

A V1 subestimava: o guard levantava antes de o componente existir e o erro sumia da contabilidade. O ledger de chamadas da Etapa 09.6 fechou a lacuna, então a V2 mede o que realmente acontece — parte do aumento é visibilidade nova, parte é degradação real do Gemini.

## Cobertura de dados

Idêntica, como esperado: 0 totalmente alinhados, 24 parciais, 26 desalinhados, 10 sem entidade, 52 temporais sem suporte. A estabilidade confirma que a auditoria é determinística.

## O que ainda não foi medido

27 casos, entre eles os 4 com alvo `mixed` e os 3 com alvo `unclear` — exatamente as classes onde a calibração tem maior risco de super-correção. Enquanto eles não rodarem, a validação do prompt v2 está confirmada para `execute`, `investigate` e `contextualize`, e **aberta** para `mixed` e `unclear`.
