# Etapa 09.5 — Diagnóstico por componente e decisão de treinamento

Este documento classifica cada componente após a rodada DEV completa. **Nenhum treinamento é executado aqui**, e nenhuma calibração de prompt foi feita após observar os resultados.

Os limiares que produzem cada classificação estão em `app/evaluation/gates.py`, declarados antes da rodada. Métrica ausente nunca é lida como zero favorável: quando um componente não foi exercitado, o resultado é `INSUFFICIENT_EVIDENCE_TO_DECIDE`, não aprovação.

## Understanding — `PROMPT_CALIBRATION_FIRST`

| Métrica | Valor |
|---|---:|
| schema válido | 98,3% |
| `request_class_accuracy` | 66,1% |
| entity extraction F1 (geral) | 0,553 |
| entity extraction F1 (`assets`) | 0,971 |
| identificadores inventados | 0 |
| violações de `action_execution_allowed` | 0 |

A rodada **rejeita a hipótese `NO_TRAINING_NEEDED`** que as etapas anteriores carregavam. O contrato é sólido e a extração de identificadores é confiável, mas a classificação de intenção é desigual de forma sistemática:

| Classe esperada | Acurácia | Confusão dominante |
|---|---:|---|
| `investigate` | 100% | — |
| `contextualize` | 93,3% | 1 → `mixed` |
| `execute` | **0%** | 13 → `mixed` |
| `unclear` | **0%** | 2 → `investigate`, 1 → `mixed` |
| `mixed` | **0%** | 3 → `investigate` |

O erro é direcional e concentrado: `execute` colapsa inteiramente em `mixed`. Isso é comportamento de fronteira de decisão mal especificada no prompt, não falta de capacidade — o modelo distingue `investigate` perfeitamente. Calibração de prompt vem antes de fine-tuning porque a hipótese mais barata ainda não foi testada.

A segurança não depende dessa classificação: mesmo classificando `execute` como `mixed`, `requested_actions` e `action_execution_allowed=false` preservaram o bloqueio de ACTION em todos os 60 casos.

## Planner — `PROMPT_CALIBRATION_FIRST`

| Métrica | Valor |
|---|---:|
| schema válido | 91,5% |
| capabilities sugeridas | 204 |
| aplicáveis estruturalmente | 79,4% |
| desnecessárias | 20,6% |
| efetivamente executadas | 29,9% |
| cobertura de objetivo | `NEEDS_HUMAN_REVIEW` |

A classificação exige uma ressalva importante: **4 das 5 falhas de schema foram truncamento, não erro de conteúdo.** Descontado o teto de 512 tokens já corrigido, o schema válido projetado é 98,3% e sobra uma única violação genuína.

O que resta de acionável é semântico: um quinto das capabilities sugeridas não é aplicável às entidades que o Understanding extraiu, e menos de um terço do plano é executado. Adequação do objetivo permanece `NEEDS_HUMAN_REVIEW` — não existe alvo determinístico de plano neste split, e inventar um seria fabricar ground truth.

## Investigator — `DATA_PROBLEM_FIRST`

| Métrica | Valor |
|---|---:|
| válidas na primeira passagem | 94,0% |
| taxa de repair | 6,0% |
| falha após repair | **0%** |
| tool inválida | 0% |
| argumento inválido | 6,0% |
| ACTION | 0 |
| loop | 0% |
| grounded quando alcançável | 0% |

O contrato é confiável e a política determinística funciona: nenhuma decisão sobreviveu inválida, nenhuma tool fora da allowlist foi chamada, nenhuma ACTION foi proposta em 117 decisões.

A classificação é `DATA_PROBLEM_FIRST` porque os dados explicam o comportamento antes de o modelo explicar:

1. **Nenhum caso do split é `FULLY_ALIGNED`.** Zero dos 60. Nenhum descritor textual corresponde ao ativo que nomeia.
2. **Os 7 argumentos inválidos são o gap temporal.** Os campos rejeitados foram `time_window`, `hours` e `window` — parâmetros temporais que nenhuma das 10 READs possui, inventados para atender pedidos como "desde o último turno". O schema barrou corretamente; a ausência está nos dados e na superfície, não no raciocínio.
3. **As escaladas são individualmente justificadas.** Evidência em `conflict`, análises `unavailable`, cadastro `inconclusive` — a Completion Policy bloquearia um `ANSWER` citando qualquer uma delas.

Treinar o Investigator contra este split ensinaria a concluir sobre ativos cuja descrição não bate com o cadastro. Corrigir os dados vem primeiro; só depois a hipótese de prompt ou de modelo se torna testável.

Ressalva de honestidade: `grounded_completion_rate_when_reachable = 0%` é medida **estrutural**. Ela diz que um fato de cadastro poderia ser materializado, não que a pergunta do usuário poderia ser respondida por ele. As perguntas do DEV pedem interpretação técnica e comparação temporal; o cadastro não as responde. Os 17 casos marcados `ESCALATION_DESPITE_REACHABLE_GROUNDED_ANSWER` estão na fila de revisão humana justamente porque a regra não decide isso.

## Reporter — `INSUFFICIENT_EVIDENCE_TO_DECIDE`

Zero casos alcançados, por regra e não por falha: o Reporter exige `InvestigationConclusion` válida, que exige `ANSWER` aceito, que não ocorreu. Declará-lo bom ou ruim seria inventar evidência.

Existe um **risco latente identificado mas não exercitado**: o Reporter pedia 1200 tokens de saída e recebia 512 pelo mesmo defeito que truncou o Planner. O micro-piloto da Etapa 09.4F passou porque produziu um relatório de uma única claim, que coube. Um relatório com várias claims teria truncado. O defeito foi corrigido antes de qualquer nova rodada.

## Atribuição de camada

Cada problema observado recebe `primary_layer` conforme a evidência, não conforme o default da taxonomia:

| Problema | Casos | Camada | Justificativa |
|---|---:|---|---|
| Truncamento de saída | 5 | `PROVIDER` | teto de configuração, não prompt nem modelo |
| Descritor contradiz cadastro | 26 | `DATA` | texto do split versus registro da API |
| Entidade não resolvível | 10 | `DATA` | anáfora sem identificador |
| Recorte temporal inexistente | 52 | `DATA` + `TOOL` | pedido válido, superfície não expressa |
| `execute` classificado como `mixed` | 13 | `PROMPT` | fronteira de decisão mal especificada |
| Capability não aplicável | 21% | `PROMPT` | plano ignora entidades disponíveis |
| 5xx transitório | 1 | `PROVIDER` | sem retry configurado |

O default `PLANNER_ERROR → PROMPT` da taxonomia foi **sobrescrito por evidência** nos casos de truncamento. O código passou a registrar `OUTPUT_TRUNCATED` com camada `PROVIDER` para que a atribuição futura seja automática.

## Ordem recomendada

1. **Dados** — realinhar descritores do DEV ao cadastro, ou aceitar que o split mede robustez a entidade inconsistente e não capacidade diagnóstica. Decidir explicitamente qual dos dois.
2. **Superfície de tools** — decidir se recorte temporal entra no contrato das READs. Hoje 52 de 60 pedidos não têm como ser atendidos.
3. **Prompt do Understanding** — separar `execute` de `mixed`.
4. **Rodada V2** com a configuração corrigida, para medir quanto das 7 falhas e do zero de conclusões era orçamento e quanto é comportamento.
5. Só então reavaliar treinamento, com o Reporter finalmente exercitado.

Nenhum destes passos foi executado nesta etapa.
