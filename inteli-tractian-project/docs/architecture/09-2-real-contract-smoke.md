# 09.2 — Real Contract Smoke

## Rodada inicial

Foram feitas três chamadas reais para Groq `openai/gpt-oss-120b`, uma para Planner, Investigator e Reporter, exclusivamente com fixtures sintéticas. Não houve ferramenta executada, dataset, Golden Set, Holdout, TRAIN, benchmark, fallback ou ACTION.

As três falharam antes de geração: HTTP 400, registrado como `request_schema_error`, sem usage. O showcase seguro está em [09-2-real-contract-smoke.json](examples/09-2-real-contract-smoke.json).

## Diagnóstico

O adapter enviava `strict: true` para qualquer JSON Schema. A Groq exige, nesse modo, todos os campos como `required` e todos os objetos fechados. A auditoria local encontrou campos opcionais nos três contratos: Planner 2, Investigator 3 e Reporter 9. Logo, os schemas canônicos Pydantic são válidos, mas não são elegíveis para strict mode sem uma transformação que alteraria sua semântica opcional.

O adapter agora usa `strict: false` para structured output e preserva a validação local obrigatória: `LLMResponse → JSON parse → Pydantic domain contract`. A rodada `contract_smoke.v2` comprovou Planner e Investigator. O Reporter recebeu HTTP 400 do provider antes de resposta, mesmo em best-effort, porque seu schema é maior; ele passa a usar o modo nativo `json_object` e a validação Pydantic local. Para GPT-OSS, JSON Object Mode também exige `reasoning_format: hidden`; o adapter passa a incluí-lo sem expor chain-of-thought.

O diagnóstico seguinte confirmou que a resposta do Reporter chegou ao provider, mas foi truncada no teto anterior de 512 tokens: o usage reportou exatamente 512 tokens de saída. O teto Groq foi elevado para 2.048; o smoke Reporter continua solicitando somente 900 e agora registra `finish_reason`. A próxima tentativa é identificada como `contract_smoke.v3.reporter`. Nenhum prompt foi ajustado silenciosamente.

## Próximo passo, ainda não executado

Uma nova rodada exige autorização explícita: somente uma chamada Groq para Reporter com `contract_smoke.v3.reporter`. Planner e Investigator já passaram. Se o Reporter passar, o status poderá ser `READY_FOR_SMALL_MODEL_BENCHMARK`; o fluxo LangGraph mínimo continua condicionado aos três contratos aprovados.

## Status

`BLOCKED_CONTRACT_VALIDATION` até o reteste autorizado. A causa está na camada adapter/structured-output, não no provider, modelo, credencial, tool layer ou contratos de domínio.

## Reteste Gemini para preparação de benchmark

O Gemini `gemini-3.5-flash-lite` foi retestado somente com fixtures sintéticas, sem tool, API externa do domínio, dataset, Golden Set, HOLDOUT, TRAIN, benchmark, fallback ou ACTION. O Planner já havia passado na rodada inicial. O Investigator e o Reporter foram repetidos depois de ajustes delimitados ao adapter/prompt de contrato:

| Componente | Prompt | Resultado | Latência | Usage (entrada/saída/total) |
| --- | --- | --- | ---: | ---: |
| Planner | `contract_smoke.v3.planner` | PASS | 3.381,877 ms | 324 / 186 / 510 |
| Investigator | `contract_smoke.v5.investigator` | PASS | 14.310,715 ms | 581 / 155 / 736 |
| Reporter | `contract_smoke.v4.reporter` | PASS | 8.973,724 ms | 677 / 376 / 1.053 |

Para Gemini, a temperatura passou a ser `1.0`, valor recomendado para a família Gemini 3. O Reporter usa `responseJsonSchema`; o Investigator recebeu uma instrução explícita com todos os campos condicionais da decisão `tool_call`. A validação continua local e obrigatória: `LLMResponse → JSON parse → contrato Pydantic → schema aprovado da READ tool`.

Os artefatos seguros finais estão em [Investigator Gemini](examples/09-2-real-contract-smoke-investigator-v3-gemini.json) e [Reporter Gemini](examples/09-2-real-contract-smoke-reporter-v3-gemini.json). Eles contêm somente fixtures e saídas estruturadas validadas; nunca chaves ou headers.

## Readiness de benchmark

`READY_FOR_GEMINI_BENCHMARK`: os três contratos cognitivos do Gemini estão aprovados e a suíte local permanece verde. O benchmark não foi iniciado nesta etapa.

Um benchmark multi-provider completo ainda não está pronto: Cerebras permanece bloqueado por HTTP 402 de quota/entitlement, e a validação final do Reporter Groq continua uma trilha independente. Nenhuma dessas pendências bloqueia um benchmark isolado do Gemini.
