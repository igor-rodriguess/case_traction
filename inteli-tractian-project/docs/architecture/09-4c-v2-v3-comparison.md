# 09.4C — Comparação V2 × V3

| Caso | V2 | V3 | Avaliação |
| --- | --- | --- | --- |
| `syn_u_dev_0001` | 2 tools, 2 evidências, contract error | contract error antes da decisão | REGRESSED |
| `syn_u_dev_0040` | `AWAITING_USER` após 5 tools | contract error antes da decisão | REGRESSED |
| `syn_u_dev_0023` | `AWAITING_USER` | `AWAITING_REQUIRED_INFORMATION` | IMPROVED: classificação correta |
| `syn_u_dev_0049` | `AWAITING_USER` | `AWAITING_REQUIRED_INFORMATION` | IMPROVED: classificação correta |
| `syn_u_dev_0036` | `HUMAN_REQUIRED` após 6 tools | contract error antes da decisão | REGRESSED |

V3: 5 casos, 12 chamadas LLM, 0 tools, 0 evidências, 0 ReporterOutputs, 2 terminalidades válidas e 3 dead ends. Foram consumidos 18.558 tokens Groq e 7.102 Gemini; latência somada por caso de 30.422,773 ms. Não houve ACTION ou loop estrutural.

A política determinística funcionou nos testes, mas o prompt/modelo não produziu decisões válidas em três trajetórias reais. Resultado: `FIX_BEFORE_FULL_DEV`.
