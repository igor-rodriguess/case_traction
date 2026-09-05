# 09.4B — Comparação V1 × V2

V1 foi preservada em `experiments/e2e-dev-v1/`; V2 foi escrita separadamente em `experiments/e2e-dev-v2/`. O JSON estruturado está em [09-4b-v1-v2-comparison.json](examples/09-4b-v1-v2-comparison.json).

V2 eliminou os `rate_limit` registrados na V1 e permitiu que as cinco execuções chegassem ao Investigator, com 13 READ tools, Trace e Evidence Ledger reais. Ainda assim, não houve `ANSWER` grounded seguido de conclusão e Reporter: uma decisão falhou o contrato, duas trajetórias pararam sem resposta e duas pararam sem evidência. A recomendação é `FIX_BEFORE_FULL_DEV`.
