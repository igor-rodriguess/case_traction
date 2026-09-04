# 06B — Esqueleto de orquestração LangGraph

## Status

`READY_FOR_INVESTIGATOR_AGENT` — a topologia está validada por fixtures determinísticas. Não há LLM, seleção de modelo, chamada de API externa ou decisão autônoma nesta etapa.

## Por que LangGraph

LangGraph é usado somente como orquestrador explícito de estado e transições. Ele não é um agente e não escolhe investigação, ferramenta ou diagnóstico. A regra arquitetural continua: **o futuro LLM decide; LangGraph roteia; código executa**. A dependência runtime é `langgraph==1.2.11`, compatível com Python 3.12 (o pacote declara Python >=3.10 e classificador 3.12). LangChain completo não foi adicionado.

## State canônico e recursos locais

`app.investigation.InvestigationState` continua a única fonte da verdade conceitual e checkpointável. O grafo usa `GraphEnvelope`, um `TypedDict` de transporte com uma única chave `state`; ele não contém campos de domínio paralelos.

`InvestigationRuntime` fornece o `ExecutionTrace`, `EvidenceLedger` e executor vivos para uma execução local. Não há checkpointer persistente, banco, SQLite, Supabase, Redis, fila ou worker. Uma implementação futura de checkpoint deverá persistir o JSON de `InvestigationState`, restaurar recursos correlacionados pelo `trace_id` e então habilitar resume.

## Topologia

```text
START → entry → understanding_boundary → investigation_entry → investigator_boundary
                                                          ↓
                                                   decision_router
        ┌──────── CONTINUE ───────────────────────────────┘
        ├──────── TOOL_CALL → tool_executor → investigation_entry
        ├──────── ASK_USER → ask_user_boundary → END
        ├──────── ANSWER → answer_boundary → END
        └──────── ESCALATE → escalate_boundary → END

qualquer falha estrutural → failed → END
```

Os nós e seus limites são:

- `entry`: valida fase `RECEIVED`, IDs e correlação do runtime, sem alterar request.
- `understanding_boundary`: recebe `UnderstandingInput`, chama uma interface injetada e usa `attach_understanding`.
- `investigation_entry`: chama `begin_investigation` e verifica limite de passos; não analisa evidência nem escolhe tool.
- `investigator_boundary`: recebe `InvestigationState` e uma interface injetada devolve `InvestigationDecision` tipada.
- `decision_router`: roteia exclusivamente pelo enum `InvestigationDecisionType`.
- `tool_executor`: resolve somente as 10 READ tools de `get_investigator_tools()` e chama `TrackedToolExecutor`.
- boundaries `ask_user`, `answer` e `escalate`: representam parada/pause sem gerar pergunta, texto ou handoff.
- `failed`: finaliza falhas estruturadas de orquestração.

Os providers futuros entram pelas interfaces `UnderstandingBoundary` e `InvestigatorBoundary`; não existem condicionais por provider ou modelo, nem API key no state.

## Trace, evidência e falhas

Após toda tool, `synchronize_observability` deriva snapshots diretamente de `ExecutionTrace` e `EvidenceLedger`; eventos e evidências nunca são replicados manualmente. O pequeno `node_observer` opcional existe apenas para capturar o showcase de teste e não é um segundo sistema de tracing.

`partial`, `inconclusive`, `conflict` e `unavailable` são evidências semânticas: entram no ledger e retornam ao Investigator. Falhas de transporte (`timeout`, conexão e equivalentes no `ClientResult`) geram `FAILED` com `TOOL_EXECUTION_FAILURE`, preservando o trace e sem inventar evidência. Exceção de tool, state inválido, transição inválida, tool desconhecida e limites também chegam ao fluxo `failed` com erro estruturado.

## Segurança e limites

Os limites padrão permanecem `max_investigation_steps=12` e `max_tool_calls=8`. A tentativa de ultrapassá-los chega a `FAILED`, impedindo loop infinito. `ToolRequest` valida a ferramenta contra o registry de READ do Investigator; ACTIONs não têm caminho executável e continuam fora da boundary.

Não há detector de repetição semântica. As futuras políticas poderão usar `tool_name`, argumentos, `call_id` e `evidence_id` já preservados.

## Pause/resume futuro

`ASK_USER` para em `AWAITING_USER` e `ESCALATE` em `HUMAN_REQUIRED`. Em etapa posterior, LangGraph poderá usar interrupt/resume com um checkpointer aprovado; esta etapa não persiste nem retoma uma execução.

## Verificação

`tests/test_langgraph_skeleton.py` cobre tool→answer, duas tools→answer, ASK_USER, ESCALATE, quatro status semânticos, timeout de transporte, dois limites, bloqueio de ACTION e independência de provider. O showcase é gerado por `api/scripts/generate_langgraph_skeleton_example.py` em `examples/06b-langgraph-skeleton-example.json`; é explicitamente uma execução de fixtures (`understanding_source` e `investigator_source` iguais a `test_fixture`).

## Não objetivos confirmados

Não foram implementados: LLM real, seleção de modelo, Investigator Agent real, seleção autônoma de tools, Reporter/Reporter LLM, ACTION execution, Human Handoff completo, Human Gate, Judges/debate/eval final, banco persistente, Supabase, queue, workers ou RAG.

## Próximo passo

Após revisão humana, conectar uma implementação aprovada do Investigator à interface já existente, preservando a mesma topologia e os mesmos contratos de decisão.
