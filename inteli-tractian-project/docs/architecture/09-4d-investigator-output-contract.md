# Etapa 09.4D — Investigator output contract

## Diagnóstico da V3

Os três casos `syn_u_dev_0001`, `syn_u_dev_0040` e `syn_u_dev_0036` terminaram com `LLMOutputValidationError`. A V3 persistiu apenas o nome da exceção: não guardou o envelope sanitizado do provider, o conteúdo canônico, o JSON intermediário nem o `ValidationError` do Pydantic. Assim, a categoria individual histórica é **não recuperável a partir dos artefatos V3**. Atribuir retrospectivamente `INVALID_ENUM`, `EXTRA_FIELD` ou outra categoria seria fabricar evidência.

A causa observável é uma lacuna na fronteira de validação: erros de JSON, schema, invariantes de domínio e tool schema eram colapsados na mesma exceção opaca. Não foi encontrada evidência de corrupção pelo adapter Gemini; testes com `MockTransport` confirmam schema exato em `responseJsonSchema`, preservação textual de `null`, enums e arrays, e ausência de double encoding introduzido pelo adapter.

## Hardening

A fronteira agora separa:

1. `provider_output`;
2. `canonicalization`;
3. `json_extraction`;
4. `schema_validation`;
5. `domain_invariants`;
6. `tool_validation`;
7. `completion_policy`.

`InvestigatorValidationResult` preserva validade, camada, categoria, campo, mensagem sanitizada, hash do output, recoverability, retryability, provider, modelo e prompt. `LLMOutputValidationError` continua sendo a exceção de alto nível, mas carrega esse resultado estruturado. A captura sanitizada do envelope do provider não inclui headers nem credenciais.

As invariantes canônicas foram mantidas. Apenas double-encoded JSON recebe normalização determinística, porque remover uma camada de serialização não altera significado. Erro recuperável pode receber uma única chamada de repair; `FORBIDDEN_ACTION` falha imediatamente. Se o repair falhar, a execução usa escalada determinística explicitamente marcada, nunca uma decisão inventada em nome do modelo.

## Validação

- baseline anterior: 294 testes;
- novos: 21;
- regressão: 315 passed, 0 failed, 0 skipped;
- warning: 1 `DeprecationWarning` conhecido do Starlette/AnyIO;
- duração: 5,06 s.

O Contract Smoke Gemini cobriu `TOOL_CALL`, `ASK_USER`, `ANSWER`, `ESCALATE` e `CONTINUE`: 5/5 válidos na primeira passagem, repair 0%, falha pós-repair 0%, ACTION 0%, tool inválida 0% e erro de adapter 0. Gate: `READY_FOR_V4_PILOT`.

## Limitação histórica

Os outputs brutos exatos da V3 não podem ser transformados em fixtures porque nunca foram persistidos. A regressão cobre todas as classes de falha com fixtures sintéticas, sem convertê-las em labels “corretos”. A V4 passa a preservar os dados necessários para futuras reproduções.
