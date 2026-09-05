# Etapa 09.4E — comparação V3 × V4

| Caso | V3 terminal / validação / tools / evidence / Reporter | V4 terminal / validação / tools / evidence / Reporter | Resultado |
|---|---|---|---|
| `0001` | DEAD_END / opaca / 0 / 0 / não | SAFE_ESCALATION / first-pass / 2 / 2 / não | IMPROVED |
| `0040` | DEAD_END / opaca / 0 / 0 / não | SAFE_ESCALATION / first-pass / 2 / 2 / não | IMPROVED |
| `0023` | AWAITING / válida / 0 / 0 / não | AWAITING / first-pass / 0 / 0 / não | UNCHANGED |
| `0049` | AWAITING / válida / 0 / 0 / não | AWAITING / first-pass / 0 / 0 / não | UNCHANGED |
| `0036` | DEAD_END / opaca / 0 / 0 / não | AWAITING / first-pass / 0 / 0 / não | IMPROVED |

Resumo: 3 improved, 2 unchanged, 0 regressed. A taxa de dead end caiu de 60% para 0%; terminalidades válidas subiram de 40% para 100%; tool calls de 0 para 4; EvidenceRecords de 0 para 4. Reporter permaneceu em 0 porque nenhuma rodada obteve conclusão grounded suficiente.

O hardening resolveu a confiabilidade estrutural nos cinco casos, mas este piloto pequeno não comprova qualidade semântica ampla nem comportamento do Reporter. Portanto o contrato está pronto para avaliação maior, com os gaps de timestamp/evento de decisão tratados antes ou junto da próxima versão de observabilidade.
