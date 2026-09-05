# Etapa 09.7 — Decisão de calibração

## Por que esta decisão não é final

Os §25 a §29 pedem a decisão definitiva após 60 casos V2. Foram medidos 3. Declarar uma rota com 5% do split seria inventar evidência, então este documento registra o que **está** decidido, o que **continua** decidido desde a V1, e o que depende explicitamente da retomada.

Regra aplicada em todos os casos: métrica ausente não vira veredicto favorável.

Essa regra precisou ser reforçada no código durante esta etapa. O assessment automático havia declarado o Understanding `NO_TRAINING_NEEDED` a partir de três casos `contextualize` corretos — exatamente o tipo de conclusão que a avaliação existe para impedir. Foi introduzido um piso de cobertura do split (`MINIMUM_SPLIT_COVERAGE = 0,80`): abaixo dele, todo componente recebe `INSUFFICIENT_EVIDENCE_TO_DECIDE` e o status global vira `INSUFFICIENT_SPLIT_COVERAGE`. O artefato `quality-gates.json` desta rodada reflete a correção.

Pelo mesmo motivo, os veredictos de gate calculados sobre os 3 casos medidos não são interpretáveis. A exceção é `DATA_COVERAGE`, que reprova sobre a auditoria determinística dos 60 casos completos e não depende da execução.

## Understanding — `PROMPT_CALIBRATION_FIRST` (aplicada, validação E2E pendente)

A calibração foi executada e medida isoladamente: acurácia 0,70 → 0,93 em 30 casos pareados, `execute` recall 0,00 → 1,00, precisão de `investigate` 0,80 → 1,00, zero regressões.

Isso resolve o padrão que a V1 identificou. O que falta é confirmar que o ganho sobrevive ao fluxo completo, onde o `UnderstandingOutput` alimenta Planner e Investigator — os 3 casos medidos são todos `contextualize` e não exercitam a correção.

Não promovo a `NO_TRAINING_NEEDED` porque `mixed` continua com recall 0,00. Na V1 sua precisão era 0,00 por receber os 13 `execute`; o problema mudou de natureza, não desapareceu. Também não rebaixo a `TRAINING_CANDIDATE`: uma regra geral de prompt corrigiu 7 casos sem quebrar nenhum, o que é comportamento de instrução ambígua, não de incapacidade.

## Planner — `PROMPT_CALIBRATION_FIRST`, com a causa principal já removida

Das 5 falhas de schema na V1, **4 eram truncamento** por teto de 512 — configuração, não conteúdo. A reexecução controlada dos quatro deu 4/4 com schema válido, e o caso `0026` precisou de 582 tokens, acima do teto antigo, o que fecha a cadeia causal.

Descontado o truncamento, a taxa projetada de schema válido é 98,3% e resta **uma** violação genuína. Por isso truncamento **não** justifica treinamento.

O que permanece acionável é semântico e medido na V1: 20,6% das capabilities sugeridas não são aplicáveis às entidades extraídas, e menos de um terço do plano é executado. Adequação de objetivo continua `NEEDS_HUMAN_REVIEW` — não existe alvo determinístico de plano neste split.

## Investigator — `DATA_PROBLEM_FIRST`

Mantida a classificação da V1, e reforçada.

O contrato é confiável: 94,0% de validade em primeira passagem sobre 117 decisões, 0% de falha após repair, 0 tools inválidas, 0 ACTION em toda a V1. Os 3 casos da V2 deram 9/9 válidas.

A barreira não é cognitiva:

1. **Nenhum caso do split é `FULLY_ALIGNED`** — zero em 60, nas duas rodadas. Nenhum descritor textual corresponde ao ativo que nomeia.
2. **Os argumentos temporais inventados eram gap de capability.** `time_window`, `hours` e `window` não existem em nenhuma das 10 READs nem na API. Treinar o modelo a não usá-los ensinaria a contornar uma ausência que a documentação da tool agora declara.
3. **As escaladas são individualmente justificadas** — evidência em `conflict`, análises `unavailable`, cadastro `inconclusive`. A Completion Policy bloquearia um `ANSWER` citando qualquer uma delas.

Recomendar fine-tuning aqui seria ensinar o agente a concluir sobre ativos cuja descrição não bate com o cadastro.

## Reporter — `INSUFFICIENT_EVIDENCE_TO_DECIDE`

Zero casos alcançados na V1 e na V2, por regra e não por falha: exige `InvestigationConclusion` válida, que exige `ANSWER` aceito, que a cobertura de dados impede.

Registro apropriado: `REPORTER_NOT_EXERCISED_DUE_TO_DATA_COVERAGE`.

A Etapa 09.4F já comprovou tecnicamente o caminho positivo (conclusão grounded → Reporter, com preservação integral de claim e evidence ID). Um risco latente foi corrigido antes de qualquer nova rodada: o Reporter pedia 1200 tokens e recebia 512 pelo mesmo defeito que truncou o Planner. Aquele micro-piloto passou porque produziu um relatório de uma única claim.

## Distinção de camada, aplicada

Para cada `ASK_USER` e `ESCALATE` da V1, a causa primária dominante:

| Causa primária | Base observada |
|---|---|
| `DATA_COVERAGE_GAP` | 0/60 alinhados, 26 desalinhados, 10 sem entidade resolvível |
| `TOOL_CAPABILITY_GAP` | 52 pedidos temporais, 0/10 tools com filtro |
| `CONFIGURATION` | 5 das 7 falhas eram orçamento de saída |
| `PROMPT` | `execute` → `mixed` (corrigido), capability não aplicável |
| `MODEL` | nenhuma evidência sobreviveu às camadas anteriores |

Nenhum problema demonstrado até aqui aponta para capacidade do modelo.

## Rota

A rota do §29 **não é declarada** nesta etapa, por falta de base.

A leitura substantiva que a evidência sustenta hoje aproxima-se de `DATA_LIMITATION_BLOCKS_MODEL_EVALUATION`: a barreira dominante nas duas rodadas é cobertura de dados e capacidade da API, não comportamento do modelo. Mas afirmá-la como decisão exigiria os 60 casos V2, e o honesto é dizer que a V2 ainda não a confirmou.

Nenhum treinamento foi executado. `TRAIN`, `HOLDOUT` e Golden Set não foram acessados.

## Condição para fechar

Retomar a V2 até 60/60 e reavaliar. Um resultado que mudaria a leitura: se, com dados igualmente ruins, a V2 melhorar de forma relevante a taxa de terminalidade válida e reduzir falhas, isso isolaria quanto das 7 falhas da V1 era configuração e quanto é comportamento — que é exatamente a pergunta que esta etapa existe para responder.

## Status

`RUN_PAUSED_PROVIDER_QUOTA`.
