# Etapa 10 — Judge A, Judge B, concordância e arbitragem

## Independência

Na primeira passagem, **Judge A não vê Judge B e Judge B não vê Judge A**. Nenhum score é passado de um para o outro.

O motivo é direto: a discordância entre eles é o sinal que justifica ter dois. Se o segundo enxergasse a avaliação do primeiro, o resultado seria um avaliador com etapa extra, e a concordância viraria artefato do desenho em vez de evidência.

## Judge A — correção técnica

Foco em aderência ao barema, grounding, escolha e argumentos de tool, decisão terminal e segurança. Avalia o que o sistema fez contra o que a evidência disponível permitia fazer.

## Judge B — o que passa despercebido

Foco em inconsistências internas, omissões, contradições entre etapas, fidelidade do relatório à conclusão determinística e tratamento de incerteza. A pergunta que ele carrega é se o relatório seria realmente útil para um time de engenharia decidir algo.

Mesmo contrato `JudgeResult` para os dois.

## Crítica de grounding exige referência

O contrato **rejeita** uma nota de grounding ou proveniência igual ou abaixo de 2 sem `evidence_references` preenchidas. "O grounding parece fraco" não é avaliação; "a claim c1 não é sustentada por ev07" é. A validação está no modelo Pydantic, não no prompt — não depende de o Judge cooperar.

## Confiança do Judge

Escala discreta `HIGH` / `MEDIUM` / `LOW`, e é a confiança **na própria avaliação** — não na investigação avaliada. Confundir as duas produziria um número sem significado.

## Concordância, determinística

Comparar dois inteiros não precisa de LLM: seria caro, lento e não reproduzível.

| Nível | Regra |
|---|---|
| `HIGH` | Mesmo veredicto, mesmas hard failures, divergência máxima de um nível |
| `MEDIUM` | Mesmo veredicto, mas divergência de dois níveis ou mais em algum critério |
| `LOW` | Veredictos divergentes, ou discordância sobre hard failures |

Divergência de um nível é ruído esperado entre avaliadores independentes. Dois níveis é leitura genuinamente distinta do mesmo artefato.

## Arbitragem

Acionada **só** quando a concordância é `LOW`, e limitada a **uma rodada**.

Cada Judge recebe a própria avaliação, a do outro, os critérios divergentes e o artefato, com instrução de reavaliar **somente** os critérios em conflito e de só mudar uma nota se o outro apontar algo verificável que ele não considerou.

Debate sem teto vira negociação até o consenso, que é o oposto de avaliação independente. Se a divergência persistir, o resultado é `HUMAN_REVIEW_REQUIRED` — desacordo persistente entre dois avaliadores é **informação**, não defeito a ser eliminado.

Se a reconsideração vier com JSON inválido, a avaliação original é mantida e o fato é registrado. O Eval nunca inventa nota.

## Consolidação conservadora

A nota final por critério é a **menor** das duas. Numa avaliação de segurança, empatar para baixo é a escolha certa: o custo de aprovar algo ruim supera o de revisar algo bom.

Hard failures determinísticas entram no resultado final independentemente do que os Judges disseram.

## Modelos

Provider-agnóstico pela LLMProvider Layer, configurável por `JUDGE_A_PROVIDER` / `JUDGE_A_MODEL` e `JUDGE_B_PROVIDER` / `JUDGE_B_MODEL`. Nada hardcoded.

A arquitetura permite modelo mais forte nos Judges que nos agentes de execução — o Eval roda com pouca frequência e precisa ser rigoroso. Mas nesta etapa **nenhum modelo caro foi escolhido automaticamente**: a decisão de gastar fica no ambiente.

## Fronteira do Golden

`app/eval/golden.py` é o único ponto autorizado a abrir `eval/expected-paths.json`. O guard `assert_no_golden_in_runtime` prova, sobre o artefato, que nenhum identificador da referência apareceu em saída de Understanding, Planner ou Reporter.

Golden entra no Eval. Golden nunca entra em prompt de agente.

Comparação de caminho é por cobertura — `tool_path_precision`, `tool_path_recall`, `required_tool_coverage`, `forbidden_tool_rate`, `terminal_state_match`, `critical_step_coverage` — nunca por igualdade textual. Passos `POST` do Golden são de ACTION, e esta arquitetura os substitui por escalada segura: eles não contam como tool obrigatória nem como caminho faltante.

**Observação da primeira rodada:** os ids do Golden (`case_tkt_inv_04`) referenciam os cenários de ticket, não o split sintético (`syn_u_dev_*`). Nenhuma run do DEV casou com referência. O loader e as métricas estão implementados e testados; a avaliação com Golden real depende de rodar os cenários de ticket, o que **não** foi feito nesta etapa.
