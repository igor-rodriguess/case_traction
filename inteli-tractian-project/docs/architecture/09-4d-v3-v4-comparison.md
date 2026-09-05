# Etapa 09.4D — efeito do hardening na V4

| Caso | V3 | V4 | Classificação |
|---|---|---|---|
| `syn_u_dev_0001` | dead end opaco | 2 READs + escalada segura | IMPROVED |
| `syn_u_dev_0040` | dead end opaco | 2 READs + escalada segura | IMPROVED |
| `syn_u_dev_0023` | solicita informação | solicita informação | UNCHANGED |
| `syn_u_dev_0049` | solicita informação | solicita informação | UNCHANGED |
| `syn_u_dev_0036` | dead end opaco | solicita informação | IMPROVED |

Na V4, 9/9 decisões foram válidas na primeira passagem. Nenhum repair ou fail-safe contratual foi usado. Logo, a melhoria observada decorre do contrato/prompt V4 e da validação auditável, não de mascaramento por recovery.

Os providers e model IDs foram preservados. Mudaram apenas o prompt do Investigator, o diagnóstico do adapter/fronteira, o limite de saída do Investigator (500 → 700) e a temperatura estruturada do piloto (1,0 → 0,0), todos congelados antes da rodada.
