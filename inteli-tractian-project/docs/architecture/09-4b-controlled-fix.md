# 09.4B — Diagnóstico e correção controlada

Os artefatos de `experiments/e2e-dev-v1/` foram preservados antes da V2. O diagnóstico formal está em [09-4b-diagnostics.json](examples/09-4b-diagnostics.json).

V2 aplica somente três mudanças mapeadas a issues: teto Groq de 1.200 para 1.800 tokens após truncamento comprovado; espera de 20 segundos entre casos para limitar pressão de quota sem aumentar retries; e instrução explícita das invariantes condicionais do `InvestigationDecision` Gemini. Schema, tools READ, ACTION policy e limites de investigação não foram alterados.

O rate limit V1 é classificado como `RATE_LIMIT_UNKNOWN`: o adapter preservou a categoria, mas a rodada anterior não reteve HTTP/headers suficientes para inferir RPM, TPM ou RPD.
