# 09.1 — Provider Smoke Diagnostics + Recovery

## Escopo e segurança

Esta etapa diagnosticou exclusivamente os adapters Groq, Gemini e Cerebras. Nenhum benchmark, dataset DEV, TRAIN, HOLDOUT, Golden Set, fallback ou ACTION foi usado. As credenciais foram verificadas somente como `CONFIGURED`; nenhum valor, header ou corpo de erro foi registrado.

O contrato `ProviderDiagnosticResult` registra provider, modelo, estado de credencial, conectividade, HTTP status, categoria, camada de causa, retry, latência, usage quando disponível e mensagem sanitizada. O adapter preserva o HTTP status, mas nunca o corpo da resposta de erro.

## Causa da rodada inicial e correções

O primeiro smoke da Etapa 09 combinava conectividade com JSON Schema estrito e descartava HTTP status. A recuperação separa as duas coisas:

- o diagnóstico envia `Return the exact short text: OK.` sem `response_format`, `responseMimeType` ou schema;
- OpenAI-compatible e Gemini continuam usando structured output somente quando `expected_schema` é não vazio;
- o timeout do Gemini foi aumentado de 15 s para 45 s;
- erros HTTP 400, 402, 404, 401/403, 429 e 5xx agora têm categoria segura e status preservado.

Os IDs foram conferidos nas documentações oficiais já registradas na Etapa 09. Não foi necessária uma chamada extra de listagem de modelos.

## Reteste controlado

Foram feitas exatamente três novas chamadas, uma por provider, com modelo e credencial configurados:

| Provider | Resultado inicial | Resultado do reteste | HTTP | Causa | Correção / conclusão |
| --- | --- | --- | ---: | --- | --- |
| Groq / `openai/gpt-oss-120b` | `provider_failure` sem HTTP preservado | sucesso, 532.412 ms | — | adapter: o teste inicial misturava conectividade com schema estrito | request mínimo sem structured output confirmou autenticação, endpoint, modelo, parsing e `LLMResponse` |
| Gemini / `gemini-3.5-flash-lite` | timeout em 15.139 ms | falha, 1.916 ms | 503 | provider temporariamente indisponível | timeout de 45 s e request nativo mínimo funcionaram até o provider; repetir apenas com nova autorização |
| Cerebras / `gpt-oss-120b` | `provider_failure` sem HTTP preservado | falha, 270.897 ms | 402 | configuração/entitlement de quota | confirmar quota/plano da conta antes de novo reteste |

O artefato seguro está em [09-1-provider-smoke-results.json](examples/09-1-provider-smoke-results.json). Usage não foi persistido pela primeira versão do script no reteste já consumido; ele fica explicitamente `not_captured_in_initial_diagnostic_run` para Groq, em vez de ser inventado. O script corrigido preservará usage em futuras execuções.

## Plano preparado, não executado

Quando os três providers tiverem conectividade aprovada, a próxima etapa poderá executar uma amostra sintética pequena e separada para Planner, Investigator e Reporter, validando `LLMRequest → LLMResponse → Pydantic contract`. Não há autorização para executar esse contract smoke, benchmark ou seleção de modelo nesta etapa.

## Status

`READY_WITH_PARTIAL_PROVIDER_AVAILABILITY`: Groq está disponível; Gemini depende da recuperação do HTTP 503 e Cerebras de quota/entitlement. Nenhum segredo vazou.
