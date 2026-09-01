# Etapa 03A — Desenho da Tool Surface

Data da análise: 2026-08-30  
Escopo: desenho documental; nenhuma tool, agente, policy ou alteração de API foi implementada.

## 1. Executive Summary

A API possui 18 operações e o `TractianClient` preserva as 18 como capabilities de integração. Isso não significa que devam existir 18 tools expostas ao LLM: endpoint, método do client e tool têm responsabilidades diferentes.

A superfície proposta contém **15 tools candidatas**: 10 READ diretamente disponíveis ao futuro Investigator e 5 ACTION catalogadas, porém indisponíveis para execução até a definição de policy, autorização, confirmação e idempotência. Duas operações de bootstrap de empresa são candidatas a uma capability sistêmica agrupada, e a leitura do usuário corrente permanece interna.

| Classificação | Operações | Resultado de design |
|---|---:|---|
| `DIRECT_READ_TOOL` | 10 | Expor ao Investigator |
| `DIRECT_ACTION_TOOL` | 5 | Catalogar; bloquear execução até policy futura |
| `GROUP_CANDIDATE` | 2 | Agrupar em `resolve_company_context`, somente sistema |
| `INTERNAL_ONLY` | 1 | Não expor ao LLM |
| **Total** | **18** | **15 tools candidatas; 10 inicialmente utilizáveis** |

Recomendação final: **READY_WITH_DECISIONS**. O desenho está suficientemente definido para revisão humana, mas as ACTIONs não devem ser implementadas como executáveis antes das decisões da seção 13.

## 2. Design Principles

1. **Contrato observado antes do declarado.** O comportamento runtime e o client validado têm precedência sobre o OpenAPI estático quando há divergência, em especial no conflito GET/PATCH de asset.
2. **Capability não implica exposição.** O client oferece integração completa; a tool surface oferece apenas decisões úteis e seguras ao modelo.
3. **Menor autoridade necessária.** Identidade, tenant, contexto do caso e controles de execução são injetados pelo sistema, nunca escolhidos pelo LLM.
4. **`seed` não é argumento de tool.** Trata-se de controle de runtime/avaliação e deve ser fixado pelo ambiente ou omitido em produção.
5. **Evidência semântica é explícita.** O consumidor deve distinguir HTTP transport status de `complete`, `partial`, `inconclusive`, `conflict` e `unavailable`.
6. **Leituras devem apoiar uma próxima decisão.** Operações redundantes, administrativas ou de bootstrap não ganham uma tool apenas por existirem.
7. **Ações descrevem intenção, não sucesso final.** O prefixo `request_` reflete que a API atual retorna acknowledgement sem provar persistência, processamento ou handoff.
8. **Planejamento permanece observável.** Bundles largos foram evitados para que seleção de evidência, custo e sequência possam ser avaliados.
9. **Sem vazamento de avaliação.** Nenhum artefato de expected paths/evals foi usado para desenhar nomes, schemas ou políticas.

## 3. Complete Operation Inventory

| # | Client method | HTTP e endpoint | Tipo | Capacidade e dado retornado | Risco, identidade, estado e limitações |
|---:|---|---|---|---|
| 1 | `get_company` | GET `/companies/{company_id}` | READ | Metadados da empresa/tenant | Baixo; `company_id` deve vir do sistema; sem estado; contexto de bootstrap, não investigação |
| 2 | `list_company_assets` | GET `/companies/{company_id}/assets` | READ | Inventário de ativos da empresa | Médio por enumeração de tenant; `company_id` sistêmico; sem estado; pode gerar payload amplo |
| 3 | `get_current_user` | GET `/users/me` | READ | Identidade e permissões correntes | Alto se usado para o LLM escolher identidade; identidade deve vir de `RequestContext`; interno |
| 4 | `get_asset` | GET `/assets/{asset_id}` | READ | Contexto operacional e configuração do ativo | Baixo; `asset_id` do caso/LLM validado contra tenant; sem estado; não substitui séries ou baseline |
| 5 | `update_asset_config` | PATCH `/assets/{asset_id}` | ACTION | Acknowledgement de alteração solicitada | Alto; exige usuário e permissão `write`; efeito apenas solicitado; sem persistência/idempotência comprovada |
| 6 | `list_asset_analyses` | GET `/assets/{asset_id}/analyses` | READ | Resumo/lista de análises e filtro de status | Baixo; contexto de ativo; sem estado; serve à descoberta, não ao diagnóstico detalhado |
| 7 | `get_analysis` | GET `/analyses/{analysis_id}` | READ | Hipótese, achados e evidências de uma análise | Baixo; contexto do caso; sem estado; pode ser parcial/inconclusivo |
| 8 | `reprocess_analysis` | POST `/analyses/{analysis_id}/reprocess` | ACTION | Solicitação de reprocessamento | Alto; usuário + `reprocess`; solicitado, não persistido; sem job/status/deduplicação |
| 9 | `request_specialist_analysis` | POST `/analyses/{analysis_id}/request-specialist` | ACTION | Solicitação de revisão especializada | Alto; usuário + permissão; handoff não comprovado; sem fila/status/idempotência |
| 10 | `get_baseline` | GET `/assets/{asset_id}/baseline` | READ | Referência histórica do ativo/ponto | Baixo; ativo/ponto do contexto; sem estado; referência não é leitura atual |
| 11 | `get_rms` | GET `/assets/{asset_id}/rms` | READ | Indicadores agregados RMS | Baixo; ativo/ponto do contexto; sem estado; agrega sinal e não revela componentes espectrais |
| 12 | `get_spectrum` | GET `/assets/{asset_id}/spectrum` | READ | Frequências/amplitudes do espectro | Baixo; ativo/ponto do contexto; sem estado; payload técnico e sem diagnóstico automático |
| 13 | `get_data_quality` | GET `/assets/{asset_id}/data-quality` | READ | Completude/confiabilidade da evidência | Baixo; ativo/ponto do contexto; sem estado; qualidade não equivale à saúde da máquina |
| 14 | `get_model` | GET `/models/{model_id}` | READ | Metadados, versão e capacidade de modelo | Médio; `model_id` deve ser referenciado por evidência; sem estado; não comprova qualidade da análise corrente |
| 15 | `request_model_retraining` | POST `/models/{model_id}/retrain` | ACTION | Solicitação de retreinamento | Alto; usuário + permissão; efeito solicitado; sem job/status/idempotência ou validação de dataset |
| 16 | `search_knowledge` | GET `/knowledge/search` | READ | Resultados relevantes por consulta/tipo | Baixo a médio; consulta do LLM; sem estado; ranking e conteúdo podem ser insuficientes |
| 17 | `get_knowledge_document` | GET `/knowledge/{doc_id}` | READ | Documento específico por identificador | Baixo; `doc_id` preferencialmente descoberto; sem estado; pode redundar com busca atual |
| 18 | `escalate_case` | POST `/cases/{case_id}/escalate` | ACTION | Solicitação de escalonamento humano | Alto; usuário + `escalate`; handoff solicitado; sem fila/status/idempotência e risco de excesso de escalonamento |

Avaliação A–I por operação (`S` = sim, `N` = não, `P` = parcialmente/depende de policy):

- **A:** o agente precisa escolher diretamente?
- **B:** significado claro para LLM?
- **C:** há operação semelhante capaz de confundir?
- **D:** é relevante à investigação?
- **E:** é apenas detalhe técnico de integração?
- **F:** exposição direta aumenta risco desnecessário?
- **G:** existe agrupamento semanticamente defensável?
- **H:** agrupar esconderia informação útil ou prejudicaria avaliação?
- **I:** a escolha futura pode ser avaliada objetivamente?

| Operação | A | B | C | D | E | F | G | H | I | Síntese |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| `get_company` | N | S | S | P | S | S | S | N | S | Bootstrap com inventário, controlado pelo sistema |
| `list_company_assets` | N | S | S | P | S | S | S | N | S | Resolução de contexto, não enumeração pelo LLM |
| `get_current_user` | N | S | N | N | S | S | N | N | S | Preflight de identidade/autorização |
| `get_asset` | S | S | S | S | N | N | P | S | S | Contexto do ativo deve permanecer granular |
| `update_asset_config` | P | S | S | P | N | S | N | S | S | Capability válida, execução condicionada a policy |
| `list_asset_analyses` | S | S | S | S | N | N | P | S | S | Descoberta separada do detalhe |
| `get_analysis` | S | S | S | S | N | N | P | S | S | Inspeção de evidência específica |
| `reprocess_analysis` | P | S | S | P | N | S | N | S | S | Automação com custo/duplicidade próprios |
| `request_specialist_analysis` | P | S | S | S | N | S | N | S | S | Handoff ligado à análise |
| `get_baseline` | S | S | S | S | N | N | P | S | S | Referência histórica distinta de qualidade |
| `get_rms` | S | S | S | S | N | N | P | S | S | Triagem agregada distinta de spectrum |
| `get_spectrum` | S | S | S | S | N | N | P | S | S | Evidência frequencial granular |
| `get_data_quality` | S | S | S | S | N | N | P | S | S | Qualifica confiabilidade, não condição |
| `get_model` | S | S | S | S | N | P | N | S | S | Leitura de capacidade/proveniência |
| `request_model_retraining` | P | S | S | P | N | S | N | S | S | Alto impacto; somente após decisão de policy |
| `search_knowledge` | S | S | S | S | N | P | P | S | S | Descoberta por consulta |
| `get_knowledge_document` | S | S | S | S | N | N | P | S | S | Recuperação determinística separada |
| `escalate_case` | P | S | S | S | N | S | N | S | S | Handoff de caso com gate futuro |

## 4. READ Analysis

| Operação | Pergunta que ajuda a responder | Usar quando | Não usar quando / próxima decisão | Classificação |
|---|---|---|---|---|
| `get_company` | Qual é o tenant em escopo? | Bootstrap e validação de contexto | Investigação já contém ativo/tenant; alimentar contexto sistêmico | `GROUP_CANDIDATE` |
| `list_company_assets` | Quais ativos pertencem ao tenant? | Resolver referência de ativo ausente | `asset_id` já é conhecido; alimentar seleção sistêmica | `GROUP_CANDIDATE` |
| `get_current_user` | Quem está autenticado e quais permissões possui? | Construção/autorização do runtime | Nunca para o LLM escolher identidade | `INTERNAL_ONLY` |
| `get_asset` | Que ativo, sensor e configuração estou investigando? | Início da investigação ou validação de configuração | Quando é necessária evidência temporal/espectral; escolher leitura específica | `DIRECT_READ_TOOL` |
| `list_asset_analyses` | Quais análises existem para o ativo? | Descobrir análises candidatas | Quando `analysis_id` já é conhecido; abrir detalhe | `DIRECT_READ_TOOL` |
| `get_analysis` | O que uma análise específica concluiu e com qual evidência? | Examinar hipótese/resultado conhecido | Descoberta ampla; listar primeiro | `DIRECT_READ_TOOL` |
| `get_baseline` | Qual comportamento histórico serve de referência? | Comparar desvio relativo | Verificar confiabilidade dos dados; consultar data quality | `DIRECT_READ_TOOL` |
| `get_rms` | A energia agregada do sinal está elevada? | Triagem de tendência/severidade | Localizar frequências causais; usar spectrum | `DIRECT_READ_TOOL` |
| `get_spectrum` | Quais componentes de frequência estão presentes? | Diferenciar padrões de falha | Apenas medir energia agregada; usar RMS | `DIRECT_READ_TOOL` |
| `get_data_quality` | A evidência é confiável/completa? | Antes de concluir ou quando há conflito | Diagnosticar saúde do ativo diretamente | `DIRECT_READ_TOOL` |
| `get_model` | Qual modelo/versão/capacidade produziu ou pode produzir uma análise? | Interpretar proveniência/limites do modelo | Inspecionar sinal ou pedir retreinamento sem justificativa | `DIRECT_READ_TOOL` |
| `search_knowledge` | Que conhecimento industrial é relevante para esta hipótese? | Descoberta por linguagem natural | Quando já existe `doc_id`; recuperar documento | `DIRECT_READ_TOOL` |
| `get_knowledge_document` | Qual é o conteúdo da referência identificada? | Recuperação determinística após descoberta/referência | Busca exploratória; usar search | `DIRECT_READ_TOOL` |

As leituras não devem ser chamadas em sequência fixa. O futuro Investigator deve selecionar a menor evidência capaz de reduzir incerteza e registrar tanto a resposta quanto seu estado semântico no Evidence Ledger.

## 5. ACTION Analysis

| Operação | Efeito externo pretendido | Dados e justificativa | Repetição/persistência | Gate e disponibilidade proposta |
|---|---|---|---|---|
| `update_asset_config` | Alterar configuração operacional | `asset_id`, mudanças permitidas e justificativa; usuário injetado | Repetição pode sobrescrever; API não comprova persistência/idempotência | Confirmação humana e policy `write`; indisponível inicialmente |
| `reprocess_analysis` | Disparar novo processamento | `analysis_id`, justificativa e parâmetros permitidos | Pode duplicar trabalho/custo; não há job/status/idempotency key | Gate conforme custo e duplicidade; indisponível inicialmente |
| `request_specialist_analysis` | Encaminhar análise a especialista | `analysis_id`, justificativa e contexto mínimo | Pode gerar solicitações duplicadas; handoff não comprovado | Gate humano/limite de taxa; indisponível inicialmente |
| `request_model_retraining` | Disparar fluxo de retreinamento | `model_id`, justificativa e parâmetros permitidos | Alto custo/impacto; não há dataset/job/status/idempotência | Aprovação humana forte; indisponível inicialmente |
| `escalate_case` | Escalonar caso para atuação humana | `case_id`, justificativa e contexto mínimo | Pode duplicar chamados; fila/ownership não comprovados | Gate e política de handoff; indisponível inicialmente |

Todas as ACTIONs exigem `RequestContext.user_id` injetado pelo sistema e autorização server-side. A decisão de expor o schema ao modelo é separada da autorização para executar: elas podem estar no catálogo para planejamento/auditoria sem serem ferramentas invocáveis.

## 6. Operation Classification Matrix

| Client Method | HTTP | Endpoint | READ/ACTION | Capability | Classification | Proposed Tool Name | LLM Arguments | System Injected Data | Risk | Human Gate Candidate | Grouping Candidate | Rationale |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `get_company` | GET | `/companies/{company_id}` | READ | Contexto da empresa | `GROUP_CANDIDATE` | `resolve_company_context` | Nenhum | `company_id`, tenant, seed/runtime | Baixo | Não | Sim | Bootstrap sistêmico, não decisão investigativa |
| `list_company_assets` | GET | `/companies/{company_id}/assets` | READ | Inventário do tenant | `GROUP_CANDIDATE` | `resolve_company_context` | Nenhum | `company_id`, tenant, seed/runtime | Médio | Não | Sim | Evita enumeração arbitrária e reduz escolhas de baixo valor |
| `get_current_user` | GET | `/users/me` | READ | Identidade/permissões | `INTERNAL_ONLY` | — | Nenhum | Credenciais e `RequestContext` | Alto | Não | Não | Identidade é autoridade do sistema, não argumento do modelo |
| `get_asset` | GET | `/assets/{asset_id}` | READ | Contexto do ativo | `DIRECT_READ_TOOL` | `get_asset_context` | `asset_id` | tenant, contexto, seed/runtime | Baixo | Não | Não | Contextualiza investigação sem efetuar mudança |
| `update_asset_config` | PATCH | `/assets/{asset_id}` | ACTION | Solicitar mudança de configuração | `DIRECT_ACTION_TOOL` | `request_asset_config_update` | `asset_id`, `changes`, `justification` | `user_id`, tenant, seed/runtime | Alto | Sim | Não | Capacidade distinta; nome explicita solicitação, não sucesso |
| `list_asset_analyses` | GET | `/assets/{asset_id}/analyses` | READ | Descobrir análises | `DIRECT_READ_TOOL` | `list_asset_analyses` | `asset_id`, `status?` | tenant, contexto, seed/runtime | Baixo | Não | Não | Listagem é etapa de descoberta observável |
| `get_analysis` | GET | `/analyses/{analysis_id}` | READ | Detalhar análise | `DIRECT_READ_TOOL` | `get_analysis_details` | `analysis_id` | tenant, contexto, seed/runtime | Baixo | Não | Não | Evidência detalhada difere da listagem |
| `reprocess_analysis` | POST | `/analyses/{analysis_id}/reprocess` | ACTION | Solicitar reprocessamento | `DIRECT_ACTION_TOOL` | `request_analysis_reprocessing` | `analysis_id`, `justification`, `params?` | `user_id`, tenant, seed/runtime | Alto | Sim | Não | Efeito/custo e permissão próprios |
| `request_specialist_analysis` | POST | `/analyses/{analysis_id}/request-specialist` | ACTION | Solicitar especialista | `DIRECT_ACTION_TOOL` | `request_specialist_analysis` | `analysis_id`, `justification`, `params?` | `user_id`, tenant, seed/runtime | Alto | Sim | Não | Handoff humano é decisão distinta do reprocessamento |
| `get_baseline` | GET | `/assets/{asset_id}/baseline` | READ | Obter referência histórica | `DIRECT_READ_TOOL` | `get_asset_baseline` | `asset_id`, `point_id?` | tenant, contexto, seed/runtime | Baixo | Não | Não | Responde comparação histórica específica |
| `get_rms` | GET | `/assets/{asset_id}/rms` | READ | Obter energia agregada | `DIRECT_READ_TOOL` | `get_asset_rms` | `asset_id`, `point_id?` | tenant, contexto, seed/runtime | Baixo | Não | Não | Métrica distinta e barata para triagem |
| `get_spectrum` | GET | `/assets/{asset_id}/spectrum` | READ | Obter componentes espectrais | `DIRECT_READ_TOOL` | `get_asset_spectrum` | `asset_id`, `point_id?` | tenant, contexto, seed/runtime | Baixo | Não | Não | Evidência causal/frequencial distinta de RMS |
| `get_data_quality` | GET | `/assets/{asset_id}/data-quality` | READ | Validar qualidade da evidência | `DIRECT_READ_TOOL` | `get_asset_data_quality` | `asset_id`, `point_id?` | tenant, contexto, seed/runtime | Baixo | Não | Não | Qualifica a confiança, não a condição do ativo |
| `get_model` | GET | `/models/{model_id}` | READ | Inspecionar capacidade do modelo | `DIRECT_READ_TOOL` | `get_model_capabilities` | `model_id` | tenant, contexto, seed/runtime | Médio | Não | Não | Apoia interpretação de proveniência e limites |
| `request_model_retraining` | POST | `/models/{model_id}/retrain` | ACTION | Solicitar retreinamento | `DIRECT_ACTION_TOOL` | `request_model_retraining` | `model_id`, `justification`, `params?` | `user_id`, tenant, seed/runtime | Alto | Sim | Não | Alto impacto exige capability e policy próprias |
| `search_knowledge` | GET | `/knowledge/search` | READ | Buscar conhecimento | `DIRECT_READ_TOOL` | `search_industrial_knowledge` | `query`, `knowledge_type?` | tenant, contexto, seed/runtime | Baixo–médio | Não | Não | Busca semântica é uma intenção própria |
| `get_knowledge_document` | GET | `/knowledge/{doc_id}` | READ | Recuperar referência | `DIRECT_READ_TOOL` | `get_knowledge_document` | `doc_id` | tenant, contexto, seed/runtime | Baixo | Não | Não | Recuperação determinística difere de busca |
| `escalate_case` | POST | `/cases/{case_id}/escalate` | ACTION | Solicitar escalonamento | `DIRECT_ACTION_TOOL` | `request_case_escalation` | `case_id`, `justification`, `params?` | `user_id`, tenant, seed/runtime | Alto | Sim | Não | Handoff operacional exige policy e auditoria próprias |

## 7. Candidate Tool Schemas

Os schemas abaixo são conceituais. Não representam classes Pydantic, decorators `@tool` ou implementação. IDs são strings não vazias. Campos opcionais não devem ser enviados como `null` sem necessidade.

Envelope normalizado de retorno para todas as tools:

```text
ToolResult<T> {
  transport_status: integer,
  evidence_status: complete | partial | inconclusive | conflict | unavailable,
  data: T | null,
  errors: ErrorDetail[],
  provenance: { client_method, endpoint, request_id? }
}
```

O envelope mantém separado o sucesso HTTP do significado da evidência. Um HTTP 200 pode carregar `partial`, `inconclusive`, `conflict` ou `unavailable` e não deve ser convertido em conclusão positiva.

| Tool candidata | Descrição para o modelo | Argumentos LLM | Injetado pelo sistema | Retorno `T` |
|---|---|---|---|---|
| `get_asset_context` | Obtém identidade, hierarquia e configuração do ativo antes de interpretar medições. | `asset_id: string` obrigatório | tenant, case context, seed/runtime | Asset |
| `list_asset_analyses` | Lista análises de um ativo para descobrir candidatos; não traz necessariamente evidência completa. | `asset_id: string`; `status?: enum` | tenant, context, seed/runtime | AnalysisSummary[] |
| `get_analysis_details` | Obtém hipótese, achados e evidências de uma análise conhecida. | `analysis_id: string` | tenant, context, seed/runtime | Analysis |
| `get_asset_baseline` | Obtém referência histórica para comparar o comportamento atual. | `asset_id: string`; `point_id?: string` | tenant, context, seed/runtime | Baseline |
| `get_asset_rms` | Obtém indicadores RMS agregados para triagem de tendência/severidade. | `asset_id: string`; `point_id?: string` | tenant, context, seed/runtime | RMSData |
| `get_asset_spectrum` | Obtém frequências e amplitudes para investigar padrões espectrais. | `asset_id: string`; `point_id?: string` | tenant, context, seed/runtime | SpectrumData |
| `get_asset_data_quality` | Verifica completude e confiabilidade antes de usar medições como evidência. | `asset_id: string`; `point_id?: string` | tenant, context, seed/runtime | DataQuality |
| `get_model_capabilities` | Obtém versão, finalidade e limites de um modelo referenciado pela investigação. | `model_id: string` | tenant, context, seed/runtime | ModelInfo |
| `search_industrial_knowledge` | Busca referências industriais relevantes para uma pergunta ou hipótese. | `query: string` obrigatória; `knowledge_type?: enum` | tenant, context, seed/runtime | KnowledgeSearchResult[] |
| `get_knowledge_document` | Recupera uma referência específica por ID previamente conhecido ou descoberto. | `doc_id: string` | tenant, context, seed/runtime | KnowledgeDocument |
| `request_asset_config_update` | Solicita mudança explícita de configuração; use apenas após validação e autorização. | `asset_id: string`; `changes: object` não vazio; `justification: string` substancial | `RequestContext.user_id`, tenant, policy, seed/runtime | ActionAcknowledgement |
| `request_analysis_reprocessing` | Solicita novo processamento de uma análise quando a evidência justificar custo/duplicidade. | `analysis_id: string`; `justification: string`; `params?: object` | `user_id`, tenant, policy, seed/runtime | ActionAcknowledgement |
| `request_specialist_analysis` | Solicita revisão especializada quando a automação não pode concluir com segurança. | `analysis_id: string`; `justification: string`; `params?: object` | `user_id`, tenant, policy, seed/runtime | ActionAcknowledgement |
| `request_model_retraining` | Solicita retreinamento somente diante de evidência de inadequação do modelo. | `model_id: string`; `justification: string`; `params?: object` | `user_id`, tenant, policy, seed/runtime | ActionAcknowledgement |
| `request_case_escalation` | Solicita handoff humano do caso com justificativa auditável. | `case_id: string`; `justification: string`; `params?: object` | `user_id`, tenant, policy, seed/runtime | ActionAcknowledgement |

Regras de schema recomendadas para implementação futura:

- `changes` e `params` devem usar allowlists por operação; não aceitar objetos arbitrários em produção.
- `justification` deve ser obrigatória, específica e auditável, mas seu tamanho mínimo e vocabulário ainda exigem decisão humana.
- `user_id`, permissões, tenant, credenciais e `seed` nunca aparecem no schema visível ao LLM.
- O client continua responsável por normalizar transporte/erros; a tool adiciona contexto de proveniência, sem reinterpretar o status semântico.

## 8. Tool Naming Analysis

Os nomes READ usam verbo de recuperação e substantivo inequívoco. `get_asset_context` evita confusão com séries; `get_analysis_details` distingue detalhe de listagem; `get_model_capabilities` deixa claro que a leitura não retreina nem avalia automaticamente o modelo.

Todas as ACTIONs usam `request_`. A escolha é deliberada porque o runtime atual reconhece a solicitação, mas não demonstra persistência nem conclusão. Nomes como `update_asset`, `reprocess_analysis` ou `escalate_case` induziriam o agente a declarar um efeito que não pode comprovar.

Não se recomenda sobrecarregar uma única tool com múltiplas intenções por union schema. Nomes devem permanecer estáveis mesmo que o endpoint interno seja versionado.

## 9. Ambiguities and Overlaps

- **GET e PATCH de asset:** ambos existem em runtime. O conflito no OpenAPI YAML estático é limitação de chave duplicada, não ausência do GET. Permanecem capabilities distintas: contexto READ e solicitação ACTION.
- **Lista e detalhe de análises:** listagem descobre candidatos; detalhe examina evidência. Fundi-las esconderia uma decisão útil e tornaria o retorno dependente de argumentos ambíguos.
- **RMS e spectrum:** RMS responde “quanta energia”; spectrum ajuda a responder “em quais frequências”. São complementares, não duplicados.
- **Baseline e data quality:** baseline é referência de comportamento; data quality mede se a evidência pode ser confiada. Um baseline não valida qualidade de aquisição.
- **Reprocessamento e especialista:** o primeiro pede novo processamento automatizado; o segundo inicia possível handoff humano. Custos, permissões e critérios divergem.
- **Especialista e escalonamento de caso:** especialista está vinculado a uma análise; escalonamento está vinculado ao caso e pode envolver resposta operacional mais ampla.
- **Modelo e retreinamento:** consultar metadados é READ; pedir retreinamento é ACTION de alto impacto. Nunca agrupar.
- **Busca e documento de conhecimento:** a busca é descoberta; documento é recuperação determinística. Apesar de a resposta atual de busca poder trazer conteúdo extenso, a separação preserva compatibilidade e intenção.
- **Empresa e ativos da empresa:** são contexto de bootstrap, não evidência diagnóstica. A proposta `resolve_company_context` é sistêmica e recebe IDs do runtime, não do LLM.

Agrupamentos rejeitados:

- `inspect_asset_condition` (`get_asset`, baseline, RMS, spectrum e data quality): aumenta payload, custo e latência; força consultas desnecessárias e oculta planejamento adaptativo.
- `get_analyses` (lista + detalhe): mistura descoberta e inspeção.
- `consult_knowledge` (busca + documento): exige schema de união e cria intenção ambígua.

## 10. Proposed Tool Registry

O registry futuro deve ser declarativo e separar existência, exposição e autorização. Cada entrada deve conter:

| Metadado | Finalidade |
|---|---|
| `name`, `description`, `category`, `kind` | Seleção semântica e distinção READ/ACTION |
| `client_method` | Ligação única à capability validada do client |
| `argument_schema` | Campos visíveis ao LLM e validações |
| `system_injections` | Identidade, tenant, contexto, policy e controles de runtime |
| `risk_level` | `low`, `medium` ou `high` |
| `exposure` | `exposed`, `system_only` ou `not_exposed` |
| `execution_policy` | `unrestricted`, `future_policy_required` ou `internal_only` |
| `available_to_investigator` | Disponibilidade real, distinta de presença no catálogo |
| `human_gate_candidate` | Indica necessidade de confirmação/aprovação |
| `preconditions` | Ownership, permissões, justificativa e integridade do caso |
| `output_contract` | Envelope com transporte, estado semântico, dados, erros e proveniência |
| `state_effect`, `idempotency` | Expectativa de efeito e proteção contra repetição |

Distribuição proposta:

- As 10 READ diretas: `exposed`, `unrestricted`, disponíveis ao Investigator, ainda sujeitas a tenant ownership e limites de uso.
- As 5 ACTION diretas: presentes no catálogo como `exposed`, mas `future_policy_required` e `available_to_investigator: false`.
- `resolve_company_context`: `system_only`, não selecionável pelo Investigator.
- `get_current_user`: `not_exposed`, `internal_only`.

O registry não deve importar ou executar automaticamente as ACTIONs apenas por catalogá-las. A camada de policy futura decide se uma chamada pode passar de proposta para execução.

## 11. Proposed Final Tool Surface

Catálogo direto estimado: **15 tools**.

READ inicialmente disponíveis (10):

1. `get_asset_context`
2. `list_asset_analyses`
3. `get_analysis_details`
4. `get_asset_baseline`
5. `get_asset_rms`
6. `get_asset_spectrum`
7. `get_asset_data_quality`
8. `get_model_capabilities`
9. `search_industrial_knowledge`
10. `get_knowledge_document`

ACTION catalogadas, não executáveis inicialmente (5):

1. `request_asset_config_update`
2. `request_analysis_reprocessing`
3. `request_specialist_analysis`
4. `request_model_retraining`
5. `request_case_escalation`

Fora da superfície direta:

- `get_company` + `list_company_assets` → possível `resolve_company_context`, somente sistema.
- `get_current_user` → interno à autenticação/autorização.

Impacto esperado no futuro Investigator:

- **Seleção:** descrições distinguem contexto, evidência, qualidade e referência externa.
- **Planejamento:** operações granulares permitem escolher a próxima consulta pela incerteza observada.
- **Loop:** retornos normalizados suportam continuar, reformular, parar ou propor handoff sem confundir HTTP 200 com evidência completa.
- **Evidence Ledger:** cada resultado registra proveniência, argumentos efetivos, transporte e estado semântico.
- **Avaliação:** escolhas continuam observáveis sem codificar trajetórias esperadas no design.
- **Segurança:** identidade e tenant ficam fora do controle do modelo; ACTIONs permanecem gated.
- **Handoff:** `request_` e acknowledgement impedem alegação prematura de conclusão externa.

## 12. Risks

1. **Autorização multi-tenant insuficiente:** IDs fornecidos pelo modelo podem acessar recursos fora do caso se ownership não for validado server-side.
2. **HTTP 200 semanticamente problemático:** `partial`, `inconclusive`, `conflict` e `unavailable` podem ser tratados como sucesso substantivo se o envelope for ignorado.
3. **ACTION sem persistência:** acknowledgement pode ser narrado como efeito concluído.
4. **Repetição não idempotente:** retries podem duplicar reprocessamentos, tickets, retraining ou mudanças.
5. **Schemas abertos:** `changes`/`params` sem allowlist ampliam autoridade e dificultam auditoria.
6. **Busca com conteúdo completo:** `get_knowledge_document` pode parecer redundante e aumentar custo até o contrato de busca ser estabilizado.
7. **Payload técnico excessivo:** spectrum e documentos podem consumir contexto; serão necessários limites/sumarização fora desta etapa.
8. **Seed exposto:** permitir que o LLM escolha `seed` comprometeria reprodutibilidade e integridade de avaliação.
9. **Descrição enviesada:** descrições prescritivas demais podem codificar caminhos de avaliação; devem explicar semântica, não uma sequência obrigatória.
10. **Gate apenas no prompt:** controles de ACTION precisam existir em código/policy server-side, não depender de obediência do modelo.

## 13. Open Decisions

Requerem decisão humana antes da implementação executável:

1. Quais ACTIONs entram no registry executável e quais permanecem apenas catalogadas?
2. Qual confirmação/Human Gate é exigido por ação, risco e ambiente?
3. `resolve_company_context` será necessário quando o caso não fornecer `asset_id`, e qual componente escolhe o ativo?
4. Quais campos e enums são permitidos em `changes` e em cada `params`?
5. Onde e como tenant ownership será validado antes de toda READ/ACTION?
6. Qual chave de idempotência, janela de deduplicação e mecanismo de consulta de status será usado nas ACTIONs?
7. O `seed` será fixado pelo ambiente de avaliação e omitido em produção?
8. `get_knowledge_document` continuará exposta se a busca mantiver documentos completos?
9. Quais limites de payload, timeout, retry e orçamento serão aplicados por tool?
10. Qual formato definitivo do Evidence Ledger consumirá o envelope normalizado?

## 14. Recommendation for Tool Implementation

**READY_WITH_DECISIONS**

É possível seguir para uma futura etapa de implementação das 10 READ tools após revisão humana deste desenho, preservando o client como única camada de acesso à API e mantendo identidade/tenant/seed fora dos argumentos do LLM.

As 5 ACTION tools podem ter schemas e metadados preparados, mas **não devem ser habilitadas para execução** até que autorização, Human Gate, allowlists, ownership, idempotência, persistência e auditoria sejam definidos. Esta etapa não implementou tools, `@tool`, LangGraph, agentes, policies, testes de tools, API ou mudanças no `TractianClient`.
