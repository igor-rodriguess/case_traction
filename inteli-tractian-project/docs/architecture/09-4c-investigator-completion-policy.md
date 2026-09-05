# 09.4C — Investigator Completion Policy

`MODEL_ROUTING_V3` preserva exatamente os providers e modelos da V2. A versão mudou porque o comportamento de conclusão foi formalizado.

## Política

- `ANSWER` somente referencia evidências existentes e semanticamente utilizáveis (`complete` ou `partial`).
- `TOOL_CALL` é aceita quando respeita limites e não repete a mesma tool com os mesmos argumentos sem nova evidência.
- `CONTINUE` exige uma READ tool planejada ainda não utilizada.
- `ASK_USER` é terminalidade válida quando a informação depende de entrada externa.
- `ESCALATE` é terminalidade válida para insuficiência, conflito, indisponibilidade, repetição ou limite sem grounding.
- Limite nunca produz `ANSWER` automaticamente.

A política não é um agente e não avalia conteúdo técnico por LLM. Ela aceita a decisão proposta ou a substitui somente por escalonamento seguro. ACTION continua indisponível.

## Conclusion handoff

Somente `ANSWER` aprovado pode gerar `InvestigationConclusion`. Toda claim deve referenciar um `EvidenceRecord` existente, correlacionável a `TraceEvent`, call ID, READ tool e origem. `ReporterInput` é criado apenas depois dessa validação.

## Validação

Foram adicionados nove testes de política/handoff, cobrindo evidence completa, partial, unavailable, conflict, informação externa, limite, answer sem evidence, repetição de tool, conclusão e referência desconhecida. A suíte passou com `294 passed` e um warning conhecido.

Os smokes Gemini também passaram:

- `SHOULD_ANSWER`: `ANSWER`, 1.357,173 ms, 694 tokens;
- `SHOULD_ESCALATE`: `ESCALATE`, 1.358,237 ms, 681 tokens.

## Limitação encontrada na V3

O piloto V3 apresentou três `LLMOutputValidationError` antes da primeira decisão. O runner registra a categoria, mas ainda não preserva o output inválido sanitizado nem a subcategoria Pydantic. Portanto, corrigir esse comportamento agora misturaria diagnóstico e experimento; a rodada foi preservada e classificada como regressão.
