# Etapa 04 — Execution Trace e Evidence Ledger

Data: 2026-08-31
Status: **READY_WITH_WARNINGS**

## Objetivo

Esta etapa adiciona observabilidade determinística à fronteira comum de execução das tools. Nenhuma tool individual passou a registrar eventos, e nenhuma lógica de investigação foi implementada.

```text
Future Investigator (não implementado)
        ↓
TrackedToolExecutor
        ├── ExecutionTrace: início
        ↓
ToolDefinition.invoke
        ↓
TractianClient → API
        ↓
ClientResult
        ├── ExecutionTrace: conclusão/resultado
        └── EvidenceLedger: evidência READ aplicável
```

## Estrutura

```text
api/app/observability/
├── __init__.py
├── models.py    # modelos imutáveis de eventos, snapshots e evidências
├── trace.py     # ExecutionTrace cronológico e append-only
├── ledger.py    # EvidenceLedger correlacionado e append-only
└── executor.py  # TrackedToolExecutor, única fronteira de instrumentação
```

## Execution Trace

Cada chamada produz dois eventos com o mesmo `call_id`:

1. `tool_started`;
2. `tool_completed` ou `tool_failed`.

O evento registra:

- `trace_id`, `call_id` e sequência cronológica;
- timestamp UTC com timezone;
- nome, categoria, READ/ACTION e operação do client;
- somente argumentos declarados no schema público da tool;
- duração em milissegundos na conclusão/falha;
- snapshot completo do `ClientResult`, incluindo transporte, `evidence_status`, dados, notas e erro;
- tipo de exceção em falhas inesperadas ou de validação.

Valores de campos extras rejeitados não são registrados. Mensagens de exceção são sanitizadas para evitar que o texto do `ValidationError` repita identidade ou outro valor proibido.

## Evidence Ledger

Um `EvidenceRecord` é criado somente quando:

- a capability é READ; e
- o `ClientResult` contém um `evidence_status` reconhecido.

Isso inclui `complete`, `partial`, `inconclusive`, `conflict` e `unavailable`. Um HTTP 200 `unavailable` continua registrado como transporte bem-sucedido e evidência semanticamente indisponível.

Falhas de transporte/protocolo permanecem no Trace, mas não viram evidência. ACTIONs também são rastreáveis caso uma camada futura já as tenha autorizado, porém nunca entram no Ledger.

Cada evidência contém `source_call_id` e `source_trace_sequence`, permitindo localizar exatamente o evento de conclusão que a originou. Também preserva tool, operação, argumentos validados, método/path HTTP, status de transporte, `evidence_status`, dados e notas.

## Determinismo e integridade

- Não existe LLM, prompt ou decisão probabilística nesta camada.
- Relógio e contador monotônico são dependências injetáveis para testes.
- IDs padrão são contadores estáveis por execução: `trace_id:call:000001` e `trace_id:evidence:000001`.
- Sequências são atribuídas pelos containers, não pelo chamador.
- Trace e Ledger devem compartilhar o mesmo `trace_id`.
- Modelos Pydantic são `frozen` e `extra="forbid"`.
- Inputs, resultados e exports recebem snapshots profundos; alterar uma estrutura retornada não modifica o histórico interno.
- Containers usam lock para preservar append e sequência sob acesso concorrente.

## Relação com policies

O `TrackedToolExecutor` observa uma `ToolDefinition` que uma camada superior já selecionou. Ele não autoriza ACTIONs, não muda `execution_policy` e não altera `get_investigator_tools()`. As cinco ACTION capabilities continuam `future_policy_required` e fora do conjunto do Investigator.

## Testes

Os testes novos cobrem:

- início, conclusão e falha;
- timestamp, sequência, duração e correlação;
- snapshot do resultado e retorno da mesma instância de `ClientResult`;
- os cinco estados semânticos;
- diferença entre `unavailable` semântico e falha de transporte;
- criação de evidência somente para READ aplicável;
- exclusão de ACTIONs do Ledger;
- sanitização de identidade em tentativa inválida;
- exceção inesperada registrada e relançada;
- proteção contra mutação externa de estruturas aninhadas;
- IDs determinísticos;
- serialização JSON;
- rejeição de `trace_id` incompatível ou vazio.

Resultado final em Python 3.12.10 e pytest 9.1.1:

| Suíte | Testes | Resultado |
|---|---:|---:|
| API original | 39 | 39 passed |
| TractianClient | 17 | 17 passed |
| Tool Layer | 37 | 37 passed |
| Trace e Evidence Ledger | 19 | 19 passed |
| **Total** | **112** | **112 passed** |

Foram **112 passed, 0 failed, 0 skipped e 1 warning em 5,91 s**. O warning é o `StarletteDeprecationWarning` preexistente na integração `fastapi.testclient`/`httpx`.

## Limitações e decisões adiadas

- armazenamento é somente em memória; persistência e retenção ainda não existem;
- não há exportador para banco, arquivo, OpenTelemetry ou serviço externo;
- payloads de evidência são preservados integralmente e poderão exigir política futura de tamanho/PII;
- não há tenant enforcement;
- não há Human Gate, idempotência ou retry de ACTIONs;
- o executor não implementa planning, investigation loop ou interpretação do Ledger;
- autenticação real, acesso concorrente distribuído e integridade criptográfica do histórico permanecem futuros.

## Não implementado

Esta etapa não introduziu LLM, LangGraph, Understanding Agent, Investigator Agent, Reporter, Human Gate, Judge, Eval, RAG, fila ou worker.
