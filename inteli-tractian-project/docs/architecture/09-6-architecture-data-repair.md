# Etapa 09.6 — Reparo de arquitetura e dados

Esta etapa corrige **apenas defeitos que a Full DEV V1 demonstrou**, e separa o que é configuração, dado, capacidade de tool, prompt e modelo antes de qualquer treinamento. Nenhum fine-tuning foi executado.

A Etapa 09.5 permanece intacta: `experiments/e2e-full-dev-v1/` não foi reescrito, e o prompt v1 continua no código, o que mantém aquela rodada reproduzível.

## 1. Teto de saída do Gemini — CONFIGURATION

`ProviderConfig.max_output_tokens` tinha default 512 e a entrada do Gemini nunca o sobrescrevia, ao contrário da do Groq, que declara 2048. Como o adapter aplica `min(request, config)`, todos os papéis roteados ao Gemini eram cortados em 512.

O corte chegava às camadas superiores como erro de schema, o que fazia o diagnóstico acusar o prompt.

**Correções**: teto do Gemini em 8192; `finish_reason` de corte (`length` na API OpenAI, `MAX_TOKENS` na Gemini) detectado antes de qualquer avaliação de JSON e devolvido como `output_truncated` na camada `configuration`, com `retryable=false`; segunda tentativa habilitada para 5xx transitório.

**Verificação causal** (`experiments/e2e-full-dev-v2-smoke/planner-token-repair.json`): os quatro Planners que a V1 truncou foram reexecutados com o `UnderstandingOutput` gravado, isolando o orçamento como única variável.

| Caso | V1 finish | V1 tokens | V2 finish | V2 tokens | Schema |
|---|---|---:|---|---:|---|
| `0025` | MAX_TOKENS | 498 | STOP | 331 | válido |
| `0026` | MAX_TOKENS | 496 | STOP | **582** | válido |
| `0034` | MAX_TOKENS | 495 | STOP | 464 | válido |
| `0051` | MAX_TOKENS | 495 | STOP | 378 | válido |

4 de 4 reparados. O caso `0026` precisou de 582 tokens — acima do teto antigo — o que confirma que 512 era a causa e não um sintoma.

## 2. Capacidade temporal das tools — TOOL CAPABILITY GAP

A matriz (`app/evaluation/tool_capabilities.py`) cruza o schema de cada tool, a assinatura do `TractianClient` e a spec da operação. Nada é declarado à mão.

| Tool | Capacidade temporal | Argumentos aceitos |
|---|---|---|
| `get_asset_context` | NONE | `asset_id` |
| `list_asset_analyses` | RETURNS_TIMESTAMPED_DATA | `asset_id`, `status` |
| `get_analysis_details` | RETURNS_TIMESTAMPED_DATA | `analysis_id` |
| `get_asset_baseline` | NONE | `asset_id`, `point_id` |
| `get_asset_rms` | RETURNS_TIMESTAMPED_DATA | `asset_id`, `point_id` |
| `get_asset_spectrum` | NONE | `asset_id`, `point_id` |
| `get_asset_data_quality` | RETURNS_TIMESTAMPED_DATA | `asset_id`, `point_id` |
| `get_model_capabilities` | RETURNS_TIMESTAMPED_DATA | `model_id` |
| `search_industrial_knowledge` | NONE | `query`, `knowledge_type` |
| `get_knowledge_document` | NONE | `doc_id` |

**Nenhuma das 10 aceita recorte temporal**, e isso é verdade na própria API: os únicos query params existentes são `seed`, `status`, `point_id`, `q` e `type`. Cinco tools devolvem dado datado, o que permite raciocinar sobre tempo sem filtrar — distinção que a política precisa preservar.

Conforme §6, **nenhum campo foi adicionado a schema algum** para o modelo passar. O schema estava certo ao rejeitar.

## 3. Temporal Request Policy — determinística

`app/investigation/temporal_policy.py` decide sem LLM:

| Situação | Reason code | Tratamento |
|---|---|---|
| Sem marcador temporal | `NO_TEMPORAL_REQUEST` | segue normalmente |
| Alguma tool filtra de verdade | `NO_TEMPORAL_REQUEST` | usa o parâmetro declarado |
| Pedido temporal + dado datado disponível | `TEMPORAL_FILTER_UNSUPPORTED` | investiga e declara a limitação |
| Referência relativa sem caminho | `TEMPORAL_CONTEXT_REQUIRED` | `ASK_USER` |
| Nem filtro nem dado datado | `TEMPORAL_DATA_UNAVAILABLE` | `ESCALATE` |

## 4. Contrato de tools informado ao Investigator

Na V1 o Investigator recebia apenas `CapabilityReference(name=...)` e precisava supor parâmetros — daí `time_window`, `hours` e `window`. `InvestigatorInput` passou a carregar `capability_contracts` com os argumentos aceitos, os obrigatórios e o JSON Schema real de cada tool, além de `temporal_guidance`.

Isso não amplia a superfície: é o mesmo schema que a Tool Layer já validava.

Argumento temporal inventado agora recebe categoria própria, `UNSUPPORTED_TEMPORAL_ARGUMENT`, separada do genérico `INVALID_TOOL_ARGUMENTS` — o que permite atribuir a camada certa.

## 5. Classificação do Understanding — PROMPT

Auditoria dos 13 casos `execute` classificados como `mixed`. Todos seguem um template: *"[verifique a situação de X]. Se houver evidência suficiente, quero [ação]; não execute nada sem a política apropriada."*

O modelo acertou tudo que importa para segurança: `requested_actions` preenchido em 13/13, intent `action_request` em 13/13, `action_execution_allowed=false` em 13/13. O erro foi só de rótulo — o prompt define `mixed` como "mais de uma classe e nenhuma dominante" e nunca declara precedência.

Uma regra ingênua "pedido de impacto → `execute`" teria degradado duas classes: os 4 casos `mixed` e 3 `unclear` **também têm `requested_actions` no alvo**. O discriminante real é a explicitude — `execute` nomeia a ação em primeira pessoa; `mixed`/`unclear` delegam ("se precisar mexer em algo, me diga"), o que é pedido de recomendação.

`understanding_prompt_v2` acrescenta apenas a precedência, sem exemplos do split, e separa explicitamente `requested_actions` de `request_class`. O v1 permanece intacto no código.

## 6. Observabilidade e métricas de provider

Duas lacunas da V1 foram fechadas:

- `components["investigator"]` é publicado **antes** do laço, para que um caso abortado preserve as decisões já tomadas;
- toda chamada de provider é gravada num ledger `llm_calls` **antes** do guard decidir abortar. Na V1 o guard levantava antes de `components[...]` existir, e o 5xx observado sumia de `provider_error_rate`, que exibiu 0 com um erro real.

A retomada também foi corrigida: um caso derrubado por quota deixou de contar como concluído e volta para a fila.

## 7. Semântica das classes

- `contextualize` — entender conceito, termo, procedimento ou critério.
- `investigate` — saber o que acontece com um ativo, se um desvio é real, ou por que algo foi detectado.
- `execute` — o cliente **nomeia** a ação de impacto que quer. Continua valendo quando condicionada a evidência. **Não** significa que o agente pode executar: `requested_actions` registra o pedido e `action_execution_allowed` permanece `false`.
- `mixed` — mais de uma classe legítima, nenhuma dominante, ação não nomeada.
- `unclear` — o desfecho pedido é vago e a entidade é apenas anafórica.

## 8. Status

`BLOCKED_BEFORE_FULL_DEV_V2`, por esgotamento de quota do provider — não por falha de qualidade. Ver `09-6-full-dev-v1-v2-comparison.md`.
