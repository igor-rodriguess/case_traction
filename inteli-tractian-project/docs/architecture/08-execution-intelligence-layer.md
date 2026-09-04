# 08 — Execution Intelligence Layer

## Fluxo e responsabilidades

`Understanding` identifica o que o usuário pede. `Planner` produz direção inicial de investigação. `Investigator` decide dinamicamente a próxima decisão estruturada usando plano e evidências. `TrackedToolExecutor` apenas executa READ tools. `Reporter` consolida um relatório técnico para o time de engenharia da TRACTIAN; não responde ao cliente, não escolhe tools e não altera evidências.

```text
Understanding → Planner → Investigator → READ Executor → Trace + Evidence
                              ↑                  │
                              └──────────────────┘
Investigator ANSWER → Conclusion → Reporter → future Eval boundary → END
```

LangGraph só transporta e roteia esses boundaries. Não é agente e não toma decisão técnica.

## Contratos canônicos

`PlannerInput` recebe Understanding, contexto permitido, capabilities READ e limites. `PlannerOutput` contém objetivos, perguntas, capabilities sugeridas, dependências, lacunas, condições de parada e reason codes. Sugestões são direções, não script imutável: o Investigator pode escolher outra READ permitida quando uma evidência mudar a investigação.

`InvestigatorInput` está preparado para compactação determinística: understanding, plano, evidência resumida, trace resumido, última observação, capabilities e counters. Não carrega transcript cru, provider metadata ou Trace inteiro. O output continua sendo `InvestigationDecision`: CONTINUE, TOOL_CALL, ASK_USER, ANSWER ou ESCALATE. ANSWER significa somente “pronto para Reporter”.

`InvestigationConclusion` reúne claims, limitações, pontos não resolvidos e referências de evidência. Cada `Claim` exige evidence IDs de suporte; não há score artificial ou chain-of-thought.

`ReporterInput` contém dados validados, conclusão e resumos. `ReporterOutput` é um relatório técnico estruturado para `tractian_engineering_team`, com findings, claims, evidências, contradições, limitações e próximos passos. Não tem registry ou executor.

## Boundaries LLM

Planner, Investigator e Reporter comunicam-se somente pela Provider Layer:

`LLMRequest → LLMProvider → LLMResponse → Pydantic output`

`PlannerLLMBoundary`, `LLMInvestigatorBoundary` e `ReporterLLMBoundary` aceitam providers injetados. A etapa usa exclusivamente `FakeLLMProvider`; não há provider/modelo real, key ou chamada externa. Model routing futuro pode fornecer providers distintos por boundary sem alterar o grafo.

## Integração e segurança

O `InvestigationState` continua canônico e ganhou campos opcionais `plan`, `conclusion` e `technical_report`, com fontes fake LLM explícitas. Não há segundo state, registry, trace ou ledger. O grafo executa Planner após Understanding quando configurado; após ANSWER anexa Conclusion e chama Reporter quando configurados. Fluxos 06B existentes continuam compatíveis quando essas boundaries não são fornecidas.

Claims e relatórios só podem referenciar evidence IDs existentes. ACTION, tool inexistente e argumentos inválidos permanecem barrados pela Provider Layer e Tool Registry antes do executor.

## Não objetivos

Não foram implementados provider real, Groq, Gemini, Cerebras, OpenRouter, chamadas externas, fine-tuning, Eval, Judges, banco, Supabase, dashboard, ACTION, filas ou workers.

## Verificação

`tests/test_execution_intelligence.py` cobre Planner, schemas inválidos, claims e um E2E determinístico com Planner fake, duas READ tools, Conclusion e Reporter fake. O showcase [08-execution-intelligence-example.json](examples/08-execution-intelligence-example.json) marca todas as fontes como fixtures/fake LLM e não representa execução real.

## Status

`READY_FOR_REAL_LLM_INTEGRATION` após revisão humana e regressão verde.
