# 09.4C — Completion diagnostics

Auditoria de `e2e-dev-v2`: `0001` terminou em `INVESTIGATING` após duas tools e um erro de contrato; `0040` terminou corretamente em `AWAITING_USER` após cinco tools; `0023` e `0049` terminaram corretamente em `AWAITING_USER` sem tool; `0036` terminou corretamente em `HUMAN_REQUIRED` após seis tools e evidência `unavailable`.

O defeito principal era de **orchestration/reporting**: o runner V2 marcava qualquer terminalidade que não fosse `ANSWER` como erro, apesar de `ASK_USER` e `ESCALATE` serem finais seguros previstos pelo contrato. A V3 formaliza `AWAITING_REQUIRED_INFORMATION` e `SAFE_ESCALATION` como terminalidades válidas; não força Reporter nesses casos.

`e2e_investigator_v3` também explicita a decisão entre evidência suficiente, informação externa e insuficiência/conflito sem ferramenta útil. Providers e modelos são iguais à V2; a versão muda apenas pelo comportamento de completion.
