# Etapa 09.8 — Groq × Gemini no Understanding

## Base

Duas evidências distintas, deliberadamente não somadas:

1. **Equivalência direta** — 10 casos DEV, mesmo input, os dois providers.
2. **Coortes de execução** — A (33 casos, Groq) e B (27 casos, Gemini), que cobrem partes diferentes do split e **não são comparáveis caso a caso**.

## Equivalência direta, mesmos 10 inputs

| Medida | Groq | Gemini |
|---|---:|---:|
| Schema válido | 10/10 | **10/10** |
| Acurácia contra o alvo | 1,00 | **1,00** |
| Concordância entre providers | — | **10/10** |
| Entidades preservadas | — | 100% |
| `requested_actions` | idênticos | idênticos |
| Violações de ACTION | 0 | 0 |
| Tokens | 42.647 | **24.976** |
| Latência | 34,8 s | 104,5 s |

Equivalência funcional confirmada. O Gemini é mais econômico em token e mais lento em parede.

Classes cobertas: `contextualize` (4), `investigate` (3), `execute` (3). `mixed` e `unclear` não existiam entre os casos já medidos com Groq.

## Understanding no split completo

Agregado das duas coortes. A métrica é do **prompt v2**, não de um provider — cada caso foi classificado uma única vez, pelo provider da sua coorte.

| Classe | n | Recall | Precisão |
|---|---:|---:|---:|
| `contextualize` | 15 | 0,93 | 1,00 |
| `investigate` | 25 | **1,00** | 0,89 |
| `execute` | 13 | **0,92** | 1,00 |
| `mixed` | 4 | 0,75 | 0,50 |
| `unclear` | 3 | **0,00** | — |

**Acurácia global: 54/60 = 0,900.**

Contra a V1, que media 0,661 com o prompt v1: `execute` saiu de 0,00 para 0,92, e o ganho global é de 24 pontos.

## O que as classes prioritárias revelaram

O §15 pediu atenção a `mixed` e `unclear`, nunca cobertas antes. O resultado separa duas situações:

**`mixed` funciona parcialmente** — recall 0,75, precisão 0,50. Três dos quatro casos foram classificados corretamente; a precisão baixa vem de um `unclear` classificado como `mixed`.

**`unclear` falha por completo** — recall 0,00, com os três casos classificados como `investigate`. A regra de precedência do prompt v2 define `unclear` como "desfecho vago E entidade apenas anafórica", mas esses casos trazem sintomas técnicos concretos ("está estranho", "talvez seja tendência radial"), e o modelo lê isso como investigação.

Esse é o único padrão de erro semântico recorrente que sobreviveu à calibração. É pequeno — 3 casos de 60 — e concentrado numa única classe.

A precisão de `investigate` cair para 0,89 é consequência direta: ela absorve os três `unclear`.

## Coortes de execução, sem comparação caso a caso

| Medida | A (Groq, 33) | B (Gemini, 27) |
|---|---:|---:|
| Terminalidade válida | 100% | 85,2% |
| Falhas comportamentais | 0 | 4 |
| `GROUNDED_COMPLETION` | 0 | **2** |
| Investigator, 1ª passagem | 100% (79 decisões) | 100% (82 decisões) |
| EvidenceRecords | 46 | 55 |
| Órfãos | 0 | 0 |
| ACTION | 0 | 0 |
| Tokens | 410.980 | 349.987 |
| Latência mediana | 42,8 s | 43,7 s |

**A diferença de terminalidade não mede provider.** As coortes cobrem casos diferentes: a B concentra os casos que a A nunca alcançou, incluindo todos os `mixed`, todos os `unclear` e a maior parte dos `execute`. As 4 falhas da B são da camada `GROUNDING` — três por fato não materializável e uma por infidelidade do Reporter — e nenhuma é atribuível ao Understanding.

Que a coorte B tenha produzido as duas únicas conclusões grounded do projeto reforça a leitura: ela recebeu os casos com mais chance de conclusão factual, não um Understanding melhor.

## Conclusão

O Gemini é aprovado como Understanding alternativo por equivalência funcional demonstrada, não por superioridade. O Groq permanece suportado e não foi removido.
