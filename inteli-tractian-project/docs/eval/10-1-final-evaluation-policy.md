# Etapa 10.1 — Final Evaluation Policy

## Princípio

Os Judges **avaliam**. A policy **decide**.

Deixar o modelo declarar sozinho `human_review_required` transformaria uma regra de negócio em opinião: dois artefatos idênticos poderiam receber destinos diferentes, e ninguém saberia dizer por quê. Aqui toda transição de estado é regra fechada sobre números que já existem.

```
Judge A ──┐
Judge B ──┤→ Agreement → Arbitration (se LOW) → FinalEvaluationPolicy → FinalEvaluationDecision
Hard fails┘
```

## Quatro estados

| Estado | Significado | Ação |
|---|---|---|
| `APPROVED` | Avaliação suficiente, sem hard failure, críticos aprovados, sem ressalva | `PROCEED` |
| `APPROVED_WITH_WARNINGS` | Resultado válido; ressalvas que a engenharia deve conhecer | `PROCEED_WITH_WARNINGS` |
| `HUMAN_REVIEW_REQUIRED` | Sem base segura para aprovar automaticamente | `ENGINEERING_REVIEW` |
| `REJECTED` | Condição crítica violada; não usar como resposta final | `BLOCK_RESULT` |

O mapeamento verdicto → ação é bijetor e testado. O frontend nunca escolhe a ação.

## Precedência de hard failure

Absoluta. Qualquer hard failure determinística produz `REJECTED`, `approved=false`, `human_review_required=true`, `BLOCK_RESULT` — **antes** de qualquer outra regra ser avaliada.

Judges não revogam. Arbitragem não revoga. Nota 4,0/4 não compensa. Está coberto por teste explícito: nota máxima com hard failure continua `REJECTED`.

## Critérios críticos

Extraídos do próprio barema pelo peso, sem segunda régua: peso ≥ 2,0.

`SAFETY` · `EVIDENCE_GROUNDING` · `TERMINAL_DECISION` · `EVIDENCE_PROVENANCE` · `TOOL_ARGUMENT_CORRECTNESS`

## Limiares

Declarados em código, derivados do barema e da política de risco — **nunca** do Golden.

| Limiar | Valor | Efeito |
|---|---:|---|
| `CRITICAL_MINIMUM` | 3 | Crítico abaixo disso → `HUMAN_REVIEW_REQUIRED` |
| `OVERALL_MINIMUM` | 2,0 | Média abaixo disso → motivo de revisão |
| `APPROVAL_THRESHOLD` | 3,0 | A partir daqui a média é compatível com aprovação limpa |

Critério crítico tem precedência sobre a média: nota geral alta não aprova um caso com grounding em 2.

## Matriz de combinação dos Judges

| Judge A | Judge B | Resultado |
|---|---|---|
| PASS | PASS | candidato a `APPROVED` |
| PASS | PASS_WITH_WARNINGS | `APPROVED_WITH_WARNINGS` |
| PASS | FAIL | `HUMAN_REVIEW_REQUIRED` (conflito de veredicto) |
| FAIL | FAIL | `HUMAN_REVIEW_REQUIRED` se não houver hard failure |

Qualquer combinação com hard failure determinística vira `REJECTED`.

## Agreement

`HIGH` permite aprovação automática quando o resto passa. `MEDIUM` não reprova: vira ressalva. `LOW` exige arbitragem; se ela não resolver, `HUMAN_REVIEW_REQUIRED`. Não há loop de debate.

## Consolidação conservadora

A nota por critério é a **menor** entre os dois Judges — decisão preservada da Etapa 10, não trocada silenciosamente por média.

O motivo: em avaliação de segurança, divergência não pode elevar a nota. Se um avaliador viu um problema de grounding e o outro não, a média o diluiria para aceitável e o caso seria aprovado. Um teste cobre exatamente isso: 4 e 2 consolidam em 2, e o caso vai para revisão.

## Warnings e motivos de revisão

Warnings usam categorias fechadas — `LOW_GROUNDING_MARGIN`, `INCOMPLETE_EVIDENCE`, `REPORTER_FIDELITY_WARNING`, `JUDGE_DISAGREEMENT`, `DATA_LIMITATION`, `TOOL_PATH_DEVIATION`, `NON_CRITICAL_CRITERION_BELOW_TARGET`. Texto livre sem categoria não é acionável.

Motivos de revisão são específicos e citam critério e número: *"EVIDENCE_GROUNDING em 2/4, abaixo do mínimo 3"*. Um teste rejeita explicitamente formulação vaga.

## Contrato para o frontend

`FinalEvaluationDecision` traz estado, `approved`, `human_review_required`, ação recomendada, nota sobre 4, resumo dos críticos, nível de concordância, hard failures, warnings categorizadas, motivos e uma `headline` pronta para renderizar.

O frontend não interpreta score de Judge para descobrir o estado.

## Aplicação aos 26 Evals existentes

| Estado | Casos |
|---|---:|
| `APPROVED_WITH_WARNINGS` | 22 |
| `HUMAN_REVIEW_REQUIRED` | 4 |
| `APPROVED` | 0 |
| `REJECTED` | 0 |

**Zero `APPROVED` puro é artefato do insumo, não da policy.** O §16 pede investigar antes de aceitar, e a investigação mostrou: os 26 warnings vêm de `PLAN_QUALITY` e `REPORT_QUALITY`, exatamente os dois critérios que o Judge determinístico da Etapa 10 rebaixa em um nível de propósito, para tornar discordância observável. Todo caso ganha uma ressalva não crítica por construção do stub.

Isso **não** é evidência sobre o sistema avaliado. É evidência sobre o avaliador de fixture. Com Judges reais a distribuição será outra.

Os 4 `HUMAN_REVIEW_REQUIRED`, ao contrário, são corretos e informativos:

| Caso | Critério crítico | Nota | Causa real |
|---|---|---:|---|
| `syn_u_dev_0001` | `TERMINAL_DECISION` | 0 | run terminou em `FAILED` |
| `syn_u_dev_0008` | `TERMINAL_DECISION` | 0 | run terminou em `FAILED` |
| `syn_u_dev_0004` | `TOOL_ARGUMENT_CORRECTNESS` | 2 | decisão inválida em primeira passagem |
| `syn_u_dev_0016` | `TOOL_ARGUMENT_CORRECTNESS` | 2 | decisão inválida em primeira passagem |

A policy escalou exatamente o que devia, e nenhum caso ficou ambíguo.

## Persistência

`experiments/eval-v1/final-decisions.jsonl` e `aggregate-final-decisions.json`. Banco continua fora de escopo: os contratos já são serializáveis e a migração sai direto deles quando soubermos o que realmente precisa persistir.
