# Etapa 09.6 — Comparação V1 × V2

## Estado da comparação

A Full DEV V2 **não foi executada**. A cota do free tier do Groq esgotou durante a etapa, e o Understanding é o primeiro passo de todo caso: sem ele, nenhum dos 60 casos avança.

O bloqueio foi caracterizado, não presumido:

| Sonda | Resultado |
|---|---|
| Conectividade Groq (16 tokens de saída) | sucesso, 361 ms |
| Conectividade Gemini | sucesso, 751 ms |
| Understanding com **prompt v1 e orçamento 1800** | HTTP 429, 105 ms |
| Understanding com prompt v2 e orçamento 2048 | HTTP 429, 52 ms |

A terceira linha é a que decide: aquela é a configuração **idêntica** à que rodou com sucesso na V1. Como ela também é recusada, o bloqueio não vem de nenhuma alteração da Etapa 09.6. É consumo acumulado do dia — V1 (60 chamadas), calibração (96) e tentativas de smoke.

Conforme §25 da etapa anterior, nenhum provider foi trocado automaticamente. A rodada parou de forma limpa com `RUN_PAUSED_PROVIDER_QUOTA` após três rate limits consecutivos, e os casos afetados voltaram para a fila de pendentes.

## O que foi medido

### Teto de tokens — reparo comprovado

| Métrica | V1 | V2 |
|---|---:|---:|
| Teto efetivo do Gemini | 512 | 8192 |
| Orçamento do Planner | 900 (cortado a 512) | 1200 |
| Planners truncados | 4 | **0 de 4 reexecutados** |
| Schema válido após reparo | — | 4/4 |

### Understanding — calibração pareada

Comparação nos **mesmos 30 casos** em que V1 e V2 produziram saída. Comparar 59 casos da V1 com 30 da V2 seria inválido, então o pareamento é explícito.

| Classe | Suporte | Recall V1 | Recall V2 | Precisão V1 | Precisão V2 |
|---|---:|---:|---:|---:|---:|
| `execute` | 5 | **0,00** | **1,00** | — | 1,00 |
| `unclear` | 2 | 0,00 | **1,00** | — | 0,67 |
| `investigate` | 12 | 1,00 | 1,00 | 0,80 | **1,00** |
| `contextualize` | 10 | 0,90 | 0,90 | 1,00 | 1,00 |
| `mixed` | 1 | 0,00 | 0,00 | 0,00 | 0,00 |

Acurácia **0,70 → 0,93**. Sete casos melhoraram, um mudou lateralmente (`investigate` → `unclear`, ambos errados), **nenhum piorou**.

`mixed` continua sendo a fronteira difícil. Na V1 sua precisão era 0,00 porque recebia os 13 `execute`; o problema mudou de natureza, não desapareceu.

Os outros 30 casos caíram por rate limit. A amostra sobrevivente é definida pela posição temporal na rodada, não pelo conteúdo, mas a limitação fica declarada.

### Gap temporal

| Medida | V1 | V2 |
|---|---:|---:|
| Tools que aceitam recorte temporal | 0 de 10 | 0 de 10 |
| Argumentos temporais inventados que chegaram ao validador | 3 (`time_window`, `hours`, `window`) | não medido em rodada |
| Categoria de rejeição | `INVALID_TOOL_ARGUMENTS` | `UNSUPPORTED_TEMPORAL_ARGUMENT` |
| Contrato de argumentos entregue ao Investigator | não | sim |
| Orientação temporal entregue | não | sim |

A superfície não mudou porque **não deveria mudar**: a API não suporta o recorte. O que mudou foi informar a limitação antes, em vez de descobri-la por rejeição.

### Cobertura de dados

Inalterada, como esperado — dataset e API não foram tocados: 0 de 60 totalmente alinhados, 26 desalinhados, 10 sem entidade resolvível, 52 pedindo recorte temporal inexistente, 0 descritores corroborados.

Isso importa para a leitura: se a qualidade não melhorar na V2, a causa continua sendo dado insuficiente, não o modelo.

## O que permanece não medido

- terminalidades da V2 e taxa de terminal válido;
- taxa de `FAILED` após os reparos;
- validade de primeira passagem do Investigator com o contrato informado;
- taxas de `ASK_USER` e `ESCALATE` sob a política temporal;
- tokens, latência e custo da V2;
- se o Reporter finalmente é alcançado.

## Retomada

O runner é idempotente e resumível. Com a cota restaurada:

```
python -m scripts.run_full_dev_evaluation --smoke --execute
python -m scripts.run_full_dev_evaluation --execute
```

O smoke escreve em diretório próprio e a rodada completa retoma de `runs.jsonl`, pulando concluídos e refazendo os que a quota derrubou.

## Status

`BLOCKED_BEFORE_FULL_DEV_V2` — bloqueio operacional de provider, com todos os reparos implementados, testados offline e, no caso do teto de tokens, comprovados causalmente contra os casos reais que falharam.
