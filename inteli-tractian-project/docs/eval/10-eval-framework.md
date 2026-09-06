# Etapa 10 — Eval Framework

## Objetivo

Responder, depois da execução: *a investigação produzida foi tecnicamente boa, bem fundamentada, segura e coerente com o comportamento esperado?*

O Eval **observa e mede**. Ele não corrige a execução retrospectivamente.

## Três conceitos separados

A confusão entre eles é a falha mais comum deste tipo de camada, e a separação é estrutural aqui:

| Conceito | O que é | Onde vive |
|---|---|---|
| **System output** | o que o pipeline realmente produziu | `experiments/*/runs.jsonl` |
| **Golden / referência** | o que se esperava para aquele caso | `eval/expected-paths.json` |
| **Barema** | os critérios usados para julgar qualidade | `eval/barema-v1.json` |

Golden não é barema. Barema não é resposta esperada. Trocar a referência não muda o que se considera qualidade, e é por isso que estão em arquivos diferentes.

## Pipeline

```
Run persistida
    ↓  adapter
EvaluationInput
    ↓
Judge A ──┐        (independentes: nenhum vê o outro)
Judge B ──┘
    ↓
Agreement (determinístico)
    ↓  só se LOW
Arbitration (uma única rodada)
    ↓
EvaluationResult
```

## O que o Eval não pode fazer

Por contrato e por construção, nenhum Judge executa tool, altera Evidence Ledger ou Trace, reexecuta o Investigator, ou modifica conclusão e relatório. Os modelos são `frozen`, e o Eval lê artefato serializado — não há objeto vivo para mutar.

## EvaluationInput

Carrega requisição original, saídas de Understanding e Planner, decisões do Investigator, resumo do Trace, EvidenceRecords com proveniência, conclusão, lineage, relatório, estado terminal, handoff e referência opcional.

Não carrega raciocínio interno, credencial ou payload bruto de evidência. Das evidências o Eval recebe os **nomes dos campos** presentes (`data_fields`), suficiente para julgar materialização sem transportar medição inteira. Um validador rejeita a construção se um campo de raciocínio aparecer.

## Escala

0–4, com semântica declarada para cada nível: falha, fraco, parcial, aceitável, forte. Nenhum score sem significado.

## Persistência

`experiments/eval-v1/` com `manifest.json`, `evaluations.jsonl`, `judge-results.jsonl`, `aggregate-metrics.json` e `errors.jsonl`.

**Banco não foi criado nesta etapa, deliberadamente.** Primeiro é preciso saber quais campos realmente precisam persistir; criar schema antes disso é adivinhar. Os contratos já são serializáveis e a migração futura provável — `evaluations`, `judge_results`, `evaluation_scores`, `evaluation_disagreements`, `evaluation_references` — sai direto deles.

## Primeira validação

26 runs reais avaliadas offline, com Judges determinísticos derivados das regras do barema. Serve para validar o **contrato** do framework sem gastar chamada nem introduzir variância de LLM na primeira passagem. O artefato registra `judges: deterministic-rule-based` para que ninguém confunda isso com avaliação por modelo.

Resultado: 22 `PASS`, 4 `PASS_WITH_WARNINGS`, concordância `HIGH` em 26/26, zero hard failures, média ponderada 3,36.
