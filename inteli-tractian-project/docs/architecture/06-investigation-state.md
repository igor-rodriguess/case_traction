# Etapa 06 — InvestigationState

Data: 2026-09-02

## 1. Purpose

`InvestigationState` é o contrato tipado que responde: **“em que situação operacional este caso está agora?”** Ele será o objeto checkpointável transportado futuramente pelo LangGraph entre recebimento, Understanding, investigação, decisão e saída.

Esta etapa é completamente determinística. Nenhum modelo, LLM ou seleção autônoma de tool foi implementado ou executado.

## 2. State vs Trace vs Evidence Ledger

| Estrutura | Pergunta respondida | Responsabilidade |
|---|---|---|
| `InvestigationState` | Em que situação está o caso agora? | fase, decisão atual, limites e referências operacionais |
| `ExecutionTrace` | O que aconteceu? | eventos cronológicos de execução das tools |
| `EvidenceLedger` | Quais evidências foram obtidas e de onde vieram? | evidências READ e sua proveniência |

O state não cria `tool_history` nem `evidence`. Ele reutiliza `TraceEvent` e `EvidenceRecord` em `TraceSnapshot` e `EvidenceLedgerSnapshot`. Os containers append-only continuam sendo a fonte de verdade durante a execução; `synchronize_observability` produz a visão serializável corrente depois do executor.

O `InvestigationRuntime` agrupa temporariamente state, `ExecutionTrace` e `EvidenceLedger`. Apenas `runtime.state` é destinado a checkpoint. Locks, cliente HTTP e executor nunca entram no state.

## 3. State schema

```text
InvestigationState
├── case_id
├── request_id
├── trace_id
├── request: UnderstandingInput
├── understanding: UnderstandingOutput | None
├── understanding_source: model | test_fixture | None
├── phase: InvestigationPhase
├── decision: InvestigationDecision | None
├── investigation_step_count / max_investigation_steps
├── tool_call_count / max_tool_calls
├── trace: TraceSnapshot<TraceEvent>
├── evidence_ledger: EvidenceLedgerSnapshot<EvidenceRecord>
├── final_response: FinalResponse | None
├── human_handoff: HumanHandoff | None
└── error: InvestigationError | None
```

Os modelos são Pydantic, `extra="forbid"` e `frozen=True`. As transições revalidam o state completo, e a restauração de JSON rejeita combinações impossíveis de fase, contadores, resposta, handoff, erro, Trace ou Ledger.

## 4. Lifecycle

```text
RECEIVED
   │ attach_understanding
   ▼
UNDERSTANDING_COMPLETE
   │ begin_investigation
   ▼
INVESTIGATING
   ├── CONTINUE  ──────────────► INVESTIGATING
   ├── TOOL_CALL ──────────────► INVESTIGATING
   ├── ASK_USER  ──────────────► AWAITING_USER
   ├── ANSWER    ──────────────► READY_FOR_RESPONSE ─► COMPLETED
   └── ESCALATE  ──────────────► HUMAN_REQUIRED

qualquer fase não terminal ────► FAILED
```

Phase e decision permanecem conceitos separados: phase informa onde o fluxo está; decision registra o que foi decidido. Transições inválidas geram `StateTransitionError`. Limites excedidos geram `LoopLimitExceeded` antes de uma nova decisão.

## 5. IDs

| ID | Identifica | Criador | Estabilidade |
|---|---|---|---|
| `case_id` | caso de negócio acompanhado | factory, ou sistema chamador quando já existe | toda a vida do caso, inclusive futuras solicitações relacionadas |
| `request_id` | solicitação original preservada neste state | factory, ou camada de entrada | toda a execução originada pela solicitação; uma clarificação futura pode ter outro request ID |
| `trace_id` | uma execução investigativa observável | factory ou infraestrutura de Trace | compartilhado pelo state, Trace, Ledger, call IDs e evidence IDs durante a execução |

A factory gera IDs UUID prefixados quando não são fornecidos e permite reutilizar Trace/Ledger existentes somente quando os três `trace_id` coincidem.

## 6. Understanding integration

O campo `request` reutiliza `UnderstandingInput`, preservando mensagem original e `AvailableContext` permitido. Ambos são imutáveis. A mensagem não é reescrita pelo state.

Antes do Understanding:

```text
understanding=None
understanding_source=None
```

`attach_understanding` aceita um `UnderstandingOutput` já tipado e registra a origem como `model` ou `test_fixture`. Nesta etapa foi usada exclusivamente `test_fixture`.

Questions, entities, missing information e investigation targets permanecem dentro de `UnderstandingOutput`; não existem cópias desses campos na raiz do state.

## 7. Future Investigator integration

O futuro Investigator será o componente autônomo que produzirá `InvestigationDecision`. O state não escolhe decisões. Os testes constroem decisões manualmente e, portanto, não simulam um agente.

O state não carrega provider, model, model ID, SDK ou configuração de inferência. Understanding, Investigator e Reporter poderão usar modelos diferentes sem mudar este contrato.

## 8. ToolRequest contract

```text
ToolRequest
├── tool_name
└── arguments: JSON
```

`ToolRequest` representa intenção de execução; não possui método de execução. `tool_name` aceita somente as dez READ tools expostas pelo registry ao Investigator. ACTION capabilities e nomes inventados são rejeitados estruturalmente.

Fluxo futuro preservado:

```text
Investigator → ToolRequest → TrackedToolExecutor → READ Tool → API
```

O teste integrado define o `ToolRequest` manualmente, usa o `TrackedToolExecutor` existente e sincroniza Trace/Ledger no state depois da execução.

## 9. Decision contract

```text
InvestigationDecision
├── decision_id
├── type: CONTINUE | TOOL_CALL | ASK_USER | ANSWER | ESCALATE
├── reason_codes[]
├── tool_request?
├── required_information[]
└── supporting_evidence_ids[]
```

`TOOL_CALL` exige `tool_request`; outros tipos o proíbem. `ASK_USER` exige `required_information`; outros tipos o proíbem. Evidence IDs referenciados precisam existir no snapshot corrente do Ledger. ACTION não é um tipo de decisão.

`decision_id` e `supporting_evidence_ids` fornecem lineage futuro. `FinalResponse` já pode referenciar `claim_ids` e evidence IDs sem implementar Claims nesta etapa.

## 10. Loop limits

Defaults explícitos:

```text
max_investigation_steps=12
max_tool_calls=8
```

`investigation_step_count` aumenta a cada decisão registrada. `tool_call_count` é derivado dos `call_id` distintos que chegaram a `tool_completed` ou `tool_failed` no Trace; não é incrementado por uma decisão isolada.

Não existe detector complexo de loop. Repetições futuras podem ser identificadas por `tool_name`, argumentos normalizados, `call_id`, sequência e produção — ou não — de novos `evidence_id` já presentes em Trace/Ledger. Não foi criado histórico duplicado para isso.

## 11. Serialization

`InvestigationState.model_dump(mode="json")`, `model_dump_json()` e `model_validate_json()` foram testados em round-trip determinístico. O state contém somente IDs, enums, modelos Pydantic, JSON, tuplas, timestamps e snapshots tipados.

O exemplo versionado foi gerado pelo código que executa o mesmo fluxo do teste integrado:

`docs/architecture/examples/06-investigation-state-example.json`

Ele inclui `understanding_source="test_fixture"`, decisão manual, dois eventos de Trace e um EvidenceRecord correlacionado.

## 12. Checkpoint readiness

O state não contém:

- conexão HTTP;
- `TractianClient`;
- `TrackedToolExecutor`;
- locks;
- closures;
- SDK de modelo;
- objetos específicos de provider.

Isso permite checkpoint, replay, debugging, avaliação, visualização e handoff sem acoplar o contrato ao runtime atual. Um checkpointer ainda não foi implementado.

## 13. Model routing readiness

Não existe campo de modelo/provider no state. Futuramente será possível rotear:

```text
Understanding → Model A
Investigator  → Model B
Reporter      → Model C
```

ou reutilizar um único modelo, sem alterar `InvestigationState`.

## 14. Why no database yet

**DATABASE_REQUIRED: NO.**

Persistência foi adiada porque o contrato ainda está sendo estabilizado, ainda precisamos observar quais estruturas realmente exigem retenção, e LangGraph/checkpoint não existe. Adicionar Supabase agora criaria schema e migrações sem uma necessidade operacional validada.

Quando replay entre processos, recuperação após falha ou retenção multiusuário se tornarem requisitos reais, a decisão deverá voltar para revisão humana como `DATABASE_REQUIRED`.

## 15. Why no LangGraph yet

LangGraph será apenas o orquestrador do lifecycle. Implementá-lo antes de congelar e revisar o contrato carregado pelo grafo esconderia decisões de estado dentro de nodes e edges. Esta etapa valida primeiro o objeto puro e suas transições.

## 16. Explicit non-goals

Não foram implementados:

- modelo real ou LLM;
- LangGraph;
- Investigator Agent;
- seleção autônoma de tools;
- Reporter Agent ou Reporter LLM;
- execução de ACTION;
- Human Gate;
- Judges ou Judge debate;
- avaliação final;
- Claims;
- Supabase ou outro banco;
- checkpointer;
- fila ou workers;
- RAG.

Também não existem campos de `reasoning`, `thoughts`, `internal_reasoning`, `chain_of_thought`, `scratchpad` ou `internal_monologue`. Auditabilidade usa reason codes, decisões, IDs, status e eventos observáveis.

## 17. Next step

Após revisão humana deste contrato, o próximo passo possível é um esqueleto de LangGraph que transporte somente `InvestigationState` e invoque transições determinísticas. Isso não autoriza Investigator, modelos, Reporter ou ACTIONs.

**Final status: READY_FOR_LANGGRAPH_SKELETON**
