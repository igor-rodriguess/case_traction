# Synthetic training dataset

Este diretório contém dados sintéticos determinísticos para os futuros componentes Understanding e Investigator. Eles seguem o design em `docs/architecture/04-6-synthetic-training-design.json` e não contêm exemplos do Golden Set.

## Conteúdo

```text
datasets/synthetic/
  dataset-manifest.json
  understanding/
    train.jsonl       # 240
    dev.jsonl         # 60
    holdout.jsonl     # 60
  investigator/
    train.jsonl       # 400
    dev.jsonl         # 100
    holdout.jsonl     # 100
```

Cada linha é um objeto JSON UTF-8 independente. As 960 amostras têm `schema_example_only=false`; os targets do Investigator nunca contêm `ACTION`, e `actions_enabled` permanece `false`.

## Reprodução

Requer somente Node.js 24 ou compatível, sem dependências externas:

```powershell
node scripts/generate-synthetic-training-data.mjs
node scripts/validate-synthetic-training-data.mjs
```

O gerador usa seed e data fixas, sobrescreve apenas `datasets/synthetic/` e deve produzir os mesmos hashes registrados no manifesto.

## Estado de aprovação

O estado atual é `GENERATED_PENDING_HUMAN_REVIEW`. As verificações determinísticas passaram, mas os campos `golden_overlap_review` permanecem `pending` de propósito. Antes de fine-tuning ou seleção de prompt, uma revisão humana estratificada deve validar plausibilidade industrial, qualidade dos labels e equivalência semântica com o Golden.

O dataset v1 recebeu aprovação limitada para o baseline e piloto do Understanding Agent em 2026-09-02. O registro auditável está em `datasets/approvals/synthetic-v1-understanding-pilot.json`. Essa decisão não aprova produção, fine-tuning do Investigator ou execução de ACTIONs e não substitui a revisão semântica linha a linha.

O split `holdout` não pode ser usado para treinamento, escolha de exemplos, ajuste de prompt ou thresholds. O Golden oficial permanece exclusivamente em `eval/` e só deve ser executado após o freeze do sistema.
