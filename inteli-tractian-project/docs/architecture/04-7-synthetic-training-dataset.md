# Etapa 04.7 — Synthetic Training Dataset

## Resultado

O desenho da Etapa 04.6 foi materializado em seis arquivos JSONL determinísticos. O dataset contém 960 amostras, sem uso de LLM e sem alteração da API, client, tools, Trace, Ledger, seeds industriais ou Golden Set.

Status: **VALIDATED_PENDING_HUMAN_REVIEW**.

Decisão de 2026-09-02: **APPROVED_FOR_UNDERSTANDING_BASELINE_PILOT**. A aprovação é limitada ao baseline e piloto do Understanding Agent; não autoriza produção, fine-tuning do Investigator ou execução de ACTIONs. O registro está em `datasets/approvals/synthetic-v1-understanding-pilot.json`.

## Inventário

| Componente | Train | Dev | Holdout | Total |
|---|---:|---:|---:|---:|
| Understanding | 240 | 60 | 60 | 360 |
| Investigator | 400 | 100 | 100 | 600 |
| Total | 640 | 160 | 160 | 960 |

O manifesto em `datasets/synthetic/dataset-manifest.json` registra caminho, quantidade, bytes e SHA-256 de cada JSONL, além das distribuições efetivas.

## Cobertura Understanding

- 90 contextualize;
- 150 investigate;
- 80 reconhecimento de execução/handoff;
- 40 mixed/unclear;
- 126 easy, 162 medium e 72 hard;
- zero mensagens exatamente duplicadas;
- referências ambíguas não revelam o asset oculto no target.

Os grupos quantitativos são mantidos em `training_tags`. Os targets usam exclusivamente os enums canônicos do schema: `contextualize`, `investigate`, `execute`, `mixed` e `unclear`.

## Cobertura Investigator

- 330 TOOL_CALL;
- 90 ASK_USER;
- 120 ANSWER;
- 60 ESCALATE;
- 0 ACTION;
- 120 pares contrafactuais;
- 120 easy, 300 medium e 180 hard;
- todos os dez READ tools aparecem nos três splits;
- zero inputs exatamente duplicados.

Os estados dominantes totalizam: 120 complete/healthy, 80 partial, 70 inconclusive, 70 conflict, 60 unavailable semântico, 60 falha de transporte/HTTP, 50 missing/ambiguous, 50 tenant/permission e 40 stopping/redundancy.

As dez categorias negativas atingem suas metas de 50 a 80 exemplos e estão distribuídas proporcionalmente entre train, dev e holdout. As tags podem se sobrepor, como previsto no design.

## Segurança e anti-leakage

As validações determinísticas confirmam:

- schemas Draft 2020-12 aplicados a todas as linhas;
- IDs únicos e contagens exatas;
- assets disjuntos entre splits;
- grupos contrafactuais inteiros no mesmo split;
- integridade de `evidence_refs`;
- tool calls somente com tenant validado e budget positivo;
- argumentos limitados ao schema da tool;
- `actions_enabled=false` em todas as amostras;
- nenhum target ACTION;
- nenhuma mensagem ou referência exata identificável do Golden;
- hashes reproduzíveis em execuções consecutivas.

A busca exata não substitui revisão semântica. Por isso, nenhuma amostra declara `golden_overlap_review=passed` automaticamente.

## Revisão humana necessária

Antes de usar o dataset, revisar ao menos 10% de cada componente de maneira estratificada por split, classe/decisão, dificuldade, condição dominante e categoria negativa. Todos os 120 pares contrafactuais devem ser submetidos a uma checagem automatizada e uma amostra de cada tipo deve receber revisão humana.

A revisão deve verificar:

1. plausibilidade industrial;
2. aderência da decisão à evidência disponível;
3. tool e argumentos adequados;
4. ausência de diagnóstico ou fonte fabricada;
5. separação entre HTTP/transport e evidence status;
6. ausência de equivalência semântica com casos Golden;
7. consistência dos reason codes;
8. não inferência de tenant, asset ou permissão ausente.

Somente após essa revisão o manifesto deve avançar para um estado aprovado e os campos de provenance correspondentes podem ser atualizados por um processo auditável.

## Comandos verificados

```powershell
node scripts/generate-synthetic-training-data.mjs
node scripts/validate-synthetic-training-data.mjs
```

Resultado do validador:

```text
files: 6
examples: 960
understanding: 360
investigator: 600
counterfactual_pairs: 120
action_targets: 0
exact_golden_leaks: 0
human_semantic_review: pending
```

## Próximo passo

Executar a revisão humana, congelar a versão `1.0.0` do dataset e medir primeiro o baseline prompt-only do Understanding Agent no dev/holdout sintético. Fine-tuning só deve ser iniciado se a avaliação demonstrar ganho necessário e mensurável.
