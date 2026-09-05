# 09.3 — Comparação Controlada: Groq × Gemini

## Escopo

Em 2026-09-04 foram feitas oito chamadas reais e controladas: uma para cada área (`Understanding`, `Planner`, `Investigator` e `Reporter`) em Groq `openai/gpt-oss-120b` e Gemini `gemini-3.5-flash-lite`.

Cada chamada usou somente fixture sintética canônica e validação local obrigatória. Não houve acesso a API industrial, tool, ACTION, TRAIN, HOLDOUT, Golden Set, fila, worker ou fallback. As chaves permanecem exclusivamente no `.env` local e não aparecem nos artefatos.

Este é um benchmark de contrato e operação, não uma avaliação estatística de qualidade. Há uma fixture por área; portanto, não mede generalização, qualidade semântica ampla, custo ou desempenho em produção.

## Resultado

| Área | Groq | Latência Groq | Gemini | Latência Gemini |
| --- | --- | ---: | --- | ---: |
| Understanding | PASS | 2.469,493 ms | PASS | 4.601,057 ms |
| Planner | PASS | 1.365,832 ms | PASS | 1.170,784 ms |
| Investigator | FAIL: `request_schema_error` | 1.007,241 ms | PASS | 3.413,706 ms |
| Reporter | FAIL: schema local | 1.286,573 ms | PASS | 1.701,942 ms |

Gemini teve 4 de 4 contratos válidos. Groq teve 2 de 4. Os tokens retornados foram preservados nos artefatos quando reportados pelo provider; custo em USD não foi inferido.

## Diagnósticos Groq

- **Investigator:** o provider recusou a requisição com HTTP 400, classificado de forma segura como `request_schema_error`. Não houve output ou usage a validar. A causa exata exige investigação específica do payload aceito pelo endpoint; não foi deduzida a partir de corpo bruto de erro.
- **Reporter:** o provider retornou JSON, mas a validação Pydantic local recusou o formato: campos obrigatórios do relatório ficaram ausentes na raiz e surgiu o campo extra `report`. O output foi bloqueado na fronteira; nenhuma normalização ou desempacotamento implícito foi aplicado.

## Decisão operacional

`GEMINI_RECOMMENDED_FOR_CURRENT_BENCHMARK`: Gemini é o único dos dois providers validado em todas as áreas nesta rodada. Groq continua elegível apenas para Understanding e Planner enquanto Investigator e Reporter não passarem novamente.

O próximo benchmark amplo, se aprovado, deve congelar versões de prompt/modelo e usar um conjunto sintético DEV previamente definido. Ele não deve reutilizar HOLDOUT nem Golden Set para ajuste.

## Artefatos

- [Resultado Groq](examples/09-3-provider-comparison.json)
- [Resultado Gemini](examples/09-3-provider-comparison-gemini.json)
