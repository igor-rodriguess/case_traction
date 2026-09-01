# Etapa 03B — Tool Layer

Data: 2026-08-31  
Status: **READY_WITH_WARNINGS**

## Responsabilidade

A Tool Layer traduz as capabilities técnicas do `TractianClient` em operações nomeadas, tipadas, determinísticas e inspecionáveis. Cada tool valida argumentos, chama exatamente um método do client e devolve o mesmo `ClientResult`, sem interpretar evidências, escolher próximos passos ou produzir uma resposta ao usuário.

```text
Future Agent (não implementado)
    ↓ seleciona somente tools autorizadas
ToolDefinition + schema Pydantic
    ↓ chama uma operação determinística
TractianClient vinculado ao RequestContext
    ↓ HTTP
API TRACTIAN
```

Não foram introduzidos LLM, agente, LangGraph, Evidence Ledger, Trace, Human Gate, Judge, Eval, RAG, fila ou worker.

## Estrutura

```text
api/app/tools/
├── __init__.py       # API pública da camada
├── base.py           # ToolDefinition, exposure e execution policy
├── schemas.py        # schemas Pydantic públicos
├── read_tools.py     # 10 wrappers READ
├── action_tools.py   # 5 wrappers ACTION
└── registry.py       # catálogos separados e inspeção determinística
```

Não foi criado framework próprio, plugin system, factory ou mecanismo de dependency injection.

## READ tools disponíveis ao Investigator

| Tool | Client operation | Diferença semântica principal |
|---|---|---|
| `get_asset_context` | `get_asset` | Contexto/configuração do ativo, não séries técnicas |
| `list_asset_analyses` | `list_asset_analyses` | Descoberta de análises, não detalhe de evidência |
| `get_analysis_details` | `get_analysis` | Detalhe de uma análise conhecida, não listagem |
| `get_asset_baseline` | `get_baseline` | Referência histórica, não qualidade da aquisição |
| `get_asset_rms` | `get_rms` | Tendência vibracional agregada, não frequências |
| `get_asset_spectrum` | `get_spectrum` | Picos/bandas de frequência, não tendência agregada |
| `get_asset_data_quality` | `get_data_quality` | Confiabilidade dos dados, não condição da máquina |
| `get_model_capabilities` | `get_model` | Cobertura/requisitos do modelo, não retreinamento |
| `search_industrial_knowledge` | `search_knowledge` | Descoberta por termos, não recuperação por ID |
| `get_knowledge_document` | `get_knowledge_document` | Recuperação determinística de documento conhecido |

As dez entradas possuem `exposure=investigator` e `execution_policy=unrestricted`. “Unrestricted” nesta camada significa que não exigem uma policy adicional de ACTION; autenticação e tenant enforcement continuam responsabilidades externas ainda não implementadas.

## ACTION capabilities catalogadas

| Capability | Client operation |
|---|---|
| `request_asset_config_update` | `update_asset_config` |
| `request_analysis_reprocessing` | `reprocess_analysis` |
| `request_specialist_analysis` | `request_specialist_analysis` |
| `request_model_retraining` | `request_model_retraining` |
| `request_case_escalation` | `escalate_case` |

Todas possuem:

- `operation_kind=ACTION`;
- `exposure=catalog_only`;
- `execution_policy=future_policy_required`.

Elas existem como wrappers tipados e testáveis, mas `get_investigator_tools()` nunca as retorna. O prefixo `request_` preserva a semântica real: a API reconhece a solicitação, mas não comprova persistência, execução ou handoff concluído.

## Schemas Pydantic

Todos os inputs herdam de `ToolInput`, configurado com `extra="forbid"`. IDs removem espaços externos e rejeitam strings vazias. A consulta de conhecimento possui limite de 500 caracteres; justificativas possuem de 20 a 2.000 caracteres.

Enums derivados do contrato real:

- análise: `current`, `stale`, `pending`, `inconclusive`;
- conhecimento: `procedure`, `glossary`, `guidance`;
- criticidade: `low`, `medium`, `high`, `critical`.

`request_asset_config_update` aceita somente a mudança `criticality`, único campo declarado no contrato estático. Os `params` das demais ACTIONs continuam abertos no runtime; por isso são representados como `dict[str, JsonValue]`, sem `Any`, e permanecem sujeitos a allowlists futuras.

Nenhum schema aceita `user_id`, `x-user-id`, headers, credenciais, identidade, `company_id` arbitrário ou `seed`.

## RequestContext

O runtime da aplicação cria o `TractianClient` com um `RequestContext` confiável e fornece esse client à `ToolDefinition.invoke`. A tool recebe apenas o client já vinculado e os argumentos validados. Assim, o LLM futuro não controla identidade ou headers, e a Tool Layer não duplica a lógica de autenticação do client.

## Preservação dos resultados

Os wrappers devolvem diretamente a instância de `ClientResult` recebida do client. Não há cópia, tradução ou ramificação por estado. Portanto permanecem separados:

- transporte: `transport_ok` e `status_code`;
- semântica: `complete`, `partial`, `inconclusive`, `conflict` ou `unavailable`;
- dados, notas e erros normalizados.

HTTP 200 com evidência problemática não é convertido em sucesso semântico.

## Registry e inspeção

Cada `ToolDefinition` registra:

- `name`;
- `category`;
- `operation_kind`;
- `description`;
- `input_schema`;
- `client_operation`;
- `exposure`;
- `execution_policy`;
- handler determinístico.

APIs públicas:

- `get_investigator_tools()` retorna exatamente as 10 READ tools;
- `get_action_tools()` retorna separadamente as 5 ACTION capabilities;
- `inspect_tool_surface()` retorna 15 objetos serializáveis com nome, descrição, JSON Schema, READ/ACTION, exposure, execution policy, categoria e operação do client.

A inspeção é determinística, não usa LLM e é coberta por teste de igualdade e serialização JSON.

## Operações internas

`get_current_user` permanece somente no `TractianClient` e não aparece em qualquer registry de tools.

`resolve_company_context` não foi implementada nesta etapa. Nenhuma das dez READ tools precisa dela para validar delegação, schemas ou resultados, e sua implementação antecipada criaria uma dependência sistêmica ainda sem consumidor. `get_company` e `list_company_assets` permanecem disponíveis no client para uma futura preparação de contexto, sem exposição ao Investigator.

## Testes

Os testes da Tool Layer usam mocks ou `httpx.MockTransport`; não dependem de LLM nem API externa.

| Suíte | Testes | Resultado |
|---|---:|---:|
| API original | 39 | 39 passed |
| TractianClient | 17 | 17 passed |
| Tool Layer | 37 | 37 passed |
| **Total** | **93** | **93 passed** |

Resultado completo em Python 3.12.10 e pytest 9.1.1: **93 passed, 0 failed, 0 skipped, 1 warning em 5,93 s** na execução final sem escrita de cache.

O warning preexistente é `StarletteDeprecationWarning` na integração `fastapi.testclient`/`httpx`; não é produzido pela Tool Layer.

## Data leakage

Nenhum arquivo em `api/app/tools/`, `TractianClient` ou `api/tests/test_tools.py` importa, abre ou referencia `eval/expected-paths.json` ou qualquer ground truth reservado. A implementação deriva somente do design aprovado, do client e dos contratos da API.

## Limitações e decisões adiadas

- Human Gate e confirmação de ACTIONs;
- autorização executável das ACTIONs;
- idempotência, deduplicação e retry sofisticado;
- tenant ownership/enforcement;
- allowlists definitivas para os objetos `params` atualmente abertos no contrato;
- Evidence Ledger, trace e telemetria;
- resolução sistêmica de contexto de empresa;
- limites de orçamento e payload;
- atualização da dependência que gera o warning de depreciação.

O ambiente `api/.venv` precisou ter o runtime CPython 3.12.10 restaurado por `uv 0.12.7`; as dependências continuaram instaladas exclusivamente no ambiente local.

## Readiness

**READY_WITH_WARNINGS**

Os critérios funcionais da Tool Layer foram atendidos. As dez READ tools estão disponíveis no conjunto do Investigator, as cinco ACTION capabilities estão isoladas por policy futura, os schemas são rígidos, identidade permanece sistêmica e a regressão completa está verde. As decisões adiadas acima não bloqueiam a camada, mas precisam ser tratadas antes de autorizar ACTIONs ou iniciar orquestração por agente.
