# 07 — LLM Provider Layer e contrato estruturado

## Objetivo

Esta etapa cria a fronteira interna entre a aplicação e futuros modelos de linguagem. A aplicação, o Investigator e o LangGraph não dependem de Groq, Gemini, Cerebras, OpenRouter, SDK, API key, header ou objeto HTTP específico. Nenhuma chamada externa foi realizada.

```text
Application / LangGraph → LLMProvider → futuro adapter de provider
                                  ↓
                           LLMResponse validada
                                  ↓
                    InvestigationDecision → Tool Registry
                                  ↓
                     TrackedToolExecutor → Trace / Ledger
```

LangGraph continua orquestrador: recebe uma decisão tipada e apenas roteia. Ele não chama provider diretamente e não decide qual tool usar.

## Contratos

`app.llm.contracts` define Pydantic estrito (`extra="forbid"`, imutável):

- `LLMRequest`: request ID, papel do agente, mensagens permitidas, versão de prompt, parâmetros de geração, schema esperado, limite de saída e timeout;
- `LLMResponse`: request/response IDs, provider, modelo, status, output JSON, uso, duração, erro, metadados e versão de contrato;
- `LLMUsage`: tokens de entrada, saída e total consistente;
- `LLMMetadata`: versão de prompt, motivo de término e ID externo opcional;
- `LLMError`: código, mensagem segura e indicação de retry.

Esses contratos não aceitam credenciais, headers arbitrários, conexão HTTP, objetos de SDK, chain-of-thought nem raciocínio privado. Provider e modelo pertencem à resposta/observabilidade de inferência, não ao `InvestigationState`.

## Provider e adapters

`LLMProvider` é um protocolo síncrono de uma única operação: `infer(LLMRequest) -> LLMResponse`. Adapters reais futuros implementam esse protocolo fora da lógica do agente. A seleção futura de modelos por papel (Understanding, Investigator, Reporter e Judge) poderá compor providers/adapters na borda de configuração, sem alterar a topologia do LangGraph; nenhum routing automático ou modelo definitivo foi criado.

`FakeLLMProvider` é uma fila determinística de `LLMResponse`. Ele registra requests para asserção e simula resposta válida, JSON inválido, schema inválido, tool inexistente, ACTION, argumentos inválidos, timeout e falha de provider sem rede, key ou SDK.

## Fronteira de decisão

`parse_investigation_decision` é a passagem obrigatória entre texto/JSON de modelo e operações. Ela:

1. aceita apenas `LLMResponse.status=success`;
2. faz parsing de string JSON quando necessário;
3. valida `InvestigationDecision` e `ToolRequest` já existentes;
4. consulta as 10 READ tools no registry existente;
5. valida argumentos pelo schema da tool autorizada.

Logo, tool inexistente, ACTION e argumentos inválidos falham antes de `TrackedToolExecutor`: o LLM não obtém acesso ao executor e nenhuma evidência ou evento de tool é fabricado. `CONTINUE`, `TOOL_CALL`, `ASK_USER`, `ANSWER` e `ESCALATE` são os únicos tipos possíveis porque o contrato anterior permanece a fonte de verdade.

`LLMInvestigatorBoundary` adapta um `LLMProvider` injetado à interface `InvestigationState -> InvestigationDecision` que o esqueleto LangGraph já consome. Ele exige que o request preserve o `request_id` do estado; não cria um segundo state.

## Observabilidade e custo

Provider layer captura provider, modelo, request ID, duração, tokens, status e erro. Isso é telemetria de inferência e não substitui `ExecutionTrace`. O Trace continua registrando execução de tools; o Evidence Ledger continua registrando somente evidência READ correlacionada. Essa separação permitirá benchmark futuro por qualidade, latência, custo, consumo, erro e tool-calling sem misturar inferência com evidência industrial.

## Relação com pause e infraestrutura

Timeout/falha do provider é resposta não executável na fronteira; o grafo poderá convertê-la posteriormente na política de retry/handoff aprovada. Não há banco, checkpointer, fila, worker ou RAG. A integração atual é local e determinística.

## Verificação e showcase

`tests/test_llm_provider_layer.py` cobre contratos, serialização, uso/metadados, JSON/schema/tool/ACTION/argumentos inválidos, falha/timeout, Fake Provider, correlação com `InvestigationState` e o fluxo Fake LLM → LangGraph → READ tool → Trace/Evidence Ledger.

O gerador `api/scripts/generate_llm_provider_example.py` produz `examples/07-llm-provider-example.json` com um `TOOL_CALL` válido e uma ACTION rejeitada. Ele não usa Golden Set como entrada de runtime.

## Não objetivos confirmados

Não foram implementados: providers reais, chamadas Groq/Gemini/Cerebras/OpenRouter, API keys, benchmark real, seleção definitiva de modelo, fine-tuning, Investigator autônomo, Reporter, Judge, Human Gate, ACTION, RAG, banco, fila ou worker.

## Status

`READY_FOR_REAL_PROVIDER` após a regressão verde: a próxima etapa pode criar um adapter real que obedeça a `LLMProvider`, sujeito à autorização explícita para credenciais e chamadas externas.
