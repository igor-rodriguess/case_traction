# Etapa 04.6 — Golden Set Audit & Synthetic Training Design

## 1. Executive Summary

Esta etapa auditou o Golden Set exclusivamente de forma offline e desenhou, sem gerar o dataset completo, a arquitetura de dados sintéticos para futuros componentes probabilísticos. Nenhum LLM foi chamado; nenhum arquivo da API, client, Tool Layer, Execution Trace, Evidence Ledger, seed ou Golden Set foi alterado.

O pacote contém 17 registros oficiais em `eval/expected-paths.json`, 16 cenários comentados e 57 operações esperadas. A diferença de contagem é intencional: `TKT-INV-09` e `TKT-EXE-12` são avaliações separadas no JSON, mas compartilham um cenário encadeado no Markdown. Os 17 casos cobrem 3 solicitações de contextualização, 9 de investigação e 5 de execução. Todas as 15 capabilities atuais aparecem ao menos uma vez.

O Golden Set é forte em trajetórias de investigação, uso de tools, raciocínio sobre evidência incompleta/conflitante e grounding. Ele não mede suficientemente desambiguação via `ASK_USER`, isolamento entre tenants, falhas reais de transporte, idempotência, repetição de ações, investigação multiativo, contexto grande ou casos saudáveis sem diagnóstico. Há também uma incompatibilidade crítica: cinco casos oficiais esperam ACTION, enquanto as ACTION capabilities atuais têm `execution_policy="future_policy_required"` e não estão disponíveis ao Investigator.

Recomendação: começar por um baseline determinístico/prompt-only do Understanding Agent e só então avaliar SFT desse componente. O Investigator é o segundo candidato, depois de congelar policy, Human Gate/simulador, schemas, reason codes e stopping policy. Reporter e camadas determinísticas não são candidatos agora.

Resultado final: **READY_WITH_DECISIONS**. Há material suficiente para iniciar um piloto sintético, mas não para gerar o dataset definitivo antes das decisões da seção 18.

## 2. Golden Set Map

Fontes auditadas: `eval/expected-paths.json`, `eval/test-scenarios.md`, `agent-input/cases.json`, `docs/support-tickets.md`, contratos e relatórios de arquitetura relevantes. `docs/test-scenarios.md` é byte a byte idêntico à cópia em `eval/` (SHA-256 `C087660173B4B0A03857848F8FE4A1F262E3CBEB57E1D6044A917BE07DCB53B9`). `README.md` e `STUDENT-GUIDE.md` citam `eval/README-eval.md`, mas esse arquivo não existe no pacote.

| Caso | Classe | Problema principal | Trajetória esperada | Decisão | Dificuldade |
|---|---|---|---|---|---|
| TKT-INV-04 | investigar | Falta de alerta antes da quebra com baseline/dados insuficientes | contexto → baseline → qualidade → RMS → escalação | escalate | hard |
| TKT-INV-05 | investigar | RMS crescente sem insight: atraso versus baixa qualidade | RMS → baseline → análises → modelo | answer | hard |
| TKT-INV-06 | investigar | Possível falso positivo com baseline invalidated | detalhe → baseline → espectro | answer | hard |
| TKT-INV-07 | investigar | Hipótese elétrica sem banda espectral decisiva | RMS → espectro | answer limitado | hard |
| TKT-INV-08 | investigar | Conflito entre diagnóstico automático e especialista | lista → detalhes → espectro | answer | hard |
| TKT-INV-09 | investigar | Análise stale após troca de rolamento | detalhe → baseline → reprocesso | action | medium |
| TKT-INV-10 | investigar | Confiança do insight sob sinal ruim | detalhe → qualidade → modelo | answer limitado | hard |
| TKT-INV-11 | investigar | Máquina suportada, mas baseline não aprendível | modelo → baseline | answer | medium |
| TKT-INV-11b | investigar | Detecção sintomática sem baseline estabelecido | detalhe → baseline → knowledge | answer | medium |
| TKT-EXE-12 | executar | Reprocesso pós-intervenção | detalhe → baseline → reprocesso | action | medium |
| TKT-EXE-16 | executar | Limite do suporte remoto | escalação com dossiê | escalate | medium |
| TKT-CTX-01 | contextualizar | Procedimento de troca sem completar conteúdo ausente | contexto → busca → documento → baseline | answer | medium |
| TKT-CTX-02 | contextualizar | Definição de BPFO e relação com o espectro | busca → documento → espectro → análises | answer | medium |
| TKT-CTX-03 | contextualizar | Limiar RMS específico versus tabela fixa | busca → baseline → RMS → qualidade | answer | hard |
| TKT-EXE-13 | executar | Solicitação de especialista com contexto suficiente | lista → detalhe → baseline → especialista | action | hard |
| TKT-EXE-14 | executar | Atualização de configuração de impacto | contexto → atualização | action | medium |
| TKT-EXE-15 | executar | Retreinamento de alto impacto exige evidência sistemática | detalhes → lista → modelo → retreinamento | action | hard |

O JSON companheiro registra, para cada caso, mensagem, perguntas implícitas, entidades, tools, evidências obrigatórias, failure modes, decisão, comportamentos proibidos e política. As trajetórias são referências avaliativas, não scripts rígidos: uma execução pode ser válida com ordem diferente se preservar parcimônia, grounding, segurança e decisão correta.

Frequência das capabilities no Golden: `get_asset_baseline` 10; `get_analysis_details` 10; `list_asset_analyses` 5; `get_asset_context`, `get_asset_rms`, `get_asset_spectrum`, `get_model_capabilities` e `search_industrial_knowledge` 4 cada; `get_asset_data_quality` 3; `get_knowledge_document`, `request_analysis_reprocessing` e `request_case_escalation` 2 cada; as outras três ACTIONs 1 cada.

## 3. Competency Taxonomy

| Competência | O que mede |
|---|---|
| request_understanding | Decomposição de intenção, perguntas, entidades, restrições e informação ausente. |
| investigation_planning | Sequenciamento adaptativo para reduzir incerteza, sem transformar o Golden em script. |
| evidence_reasoning | Uso correto de complete, partial, inconclusive, conflict e unavailable. |
| tool_use | Escolha da capability, argumentos permitidos, parcimônia e não repetição. |
| decision_policy | Escolha entre TOOL_CALL, ASK_USER, ANSWER, ESCALATE e, futuramente, proposta de ACTION. |
| safety | Tenant, permissão, impacto, justificativa, abstenção e limites de autoridade. |
| response_grounding | Cada alegação apoiada por evidência e limitações explícitas. |
| human_handoff | Escalação com dossiê útil, sem abandono prematuro nem over-escalation. |
| multi_question_multi_asset | Cobertura de todas as perguntas e ativos sem misturar evidências. |
| robustness | Ambiguidade, falha semântica/HTTP/transporte, contexto grande, stopping e recuperação. |
| action_accountability | Precondições, autorização, confirmação, idempotência e pós-condições de impacto. |

`action_accountability` foi adicionada além das competências cognitivas porque uma decisão correta de investigar não garante uma execução de impacto segura e auditável.

## 4. Golden Set Coverage Matrix

Legenda: 0 = ausente; 1 = incidental/parcial; 2 = objetivo explícito. Abreviações: RU, IP, ER, TU, DP, SF, RG, HH, MQ, RB e AA seguem a ordem da taxonomia acima.

| Caso | RU | IP | ER | TU | DP | SF | RG | HH | MQ | RB | AA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| INV-04 | 1 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 2 | 1 |
| INV-05 | 1 | 2 | 2 | 2 | 2 | 1 | 2 | 0 | 0 | 2 | 1 |
| INV-06 | 1 | 2 | 2 | 2 | 2 | 2 | 2 | 1 | 0 | 2 | 0 |
| INV-07 | 1 | 2 | 2 | 2 | 2 | 1 | 2 | 0 | 0 | 2 | 0 |
| INV-08 | 1 | 2 | 2 | 2 | 2 | 1 | 2 | 1 | 0 | 2 | 0 |
| INV-09 | 1 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 0 | 2 | 2 |
| INV-10 | 1 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 0 | 2 | 0 |
| INV-11 | 1 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 0 | 2 | 1 |
| INV-11b | 1 | 2 | 2 | 2 | 2 | 1 | 2 | 0 | 0 | 2 | 0 |
| EXE-12 | 1 | 1 | 1 | 2 | 2 | 2 | 1 | 0 | 0 | 1 | 2 |
| EXE-16 | 1 | 1 | 2 | 1 | 2 | 2 | 2 | 2 | 0 | 2 | 2 |
| CTX-01 | 1 | 2 | 1 | 2 | 1 | 1 | 2 | 0 | 1 | 2 | 0 |
| CTX-02 | 2 | 2 | 2 | 2 | 1 | 0 | 2 | 0 | 2 | 1 | 0 |
| CTX-03 | 2 | 2 | 2 | 2 | 1 | 0 | 2 | 0 | 2 | 2 | 0 |
| EXE-13 | 1 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 2 | 2 |
| EXE-14 | 1 | 1 | 1 | 2 | 2 | 2 | 1 | 0 | 0 | 2 | 2 |
| EXE-15 | 1 | 2 | 2 | 2 | 2 | 2 | 2 | 1 | 0 | 2 | 2 |

## 5. Coverage Gaps

| Severidade | Lacuna | Componente principal | Como testar |
|---|---|---|---|
| critical | Nenhum caso termina em ASK_USER | Understanding + Investigator | IDs ausentes, referência ambígua, múltiplos candidatos e pergunta mínima necessária. |
| critical | Golden espera 5 ACTIONs incompatíveis com a policy atual | Policy/Human Gate/Judge | Separar reconhecimento/proposta de execução real e exigir autorização verificável. |
| critical | Isolamento cross-tenant não é exercitado | Tool executor + safety | Mesmo ID sintático sob tenant correto/incorreto, sem vazamento. |
| critical | Repetição/idempotência de ACTION ausente | Action executor futuro | Retry, acknowledgement perdido e mesma chave idempotente. |
| high | Não há caso saudável explícito | Investigator | Evidência normal deve levar a answer grounded, sem inventar diagnóstico. |
| high | Não há investigação multiativo | Understanding + Ledger + Investigator | Dois ativos, evidências disjuntas e comparação sem contaminação. |
| high | Falhas reais de transporte/timeout/5xx ausentes | Client/Investigator | Distinguir transporte de HTTP e `evidence_status`. |
| high | Grounding não é avaliado por claim atômica | Investigator/Reporter | Cada claim referencia `evidence_id`; claim sem suporte falha. |
| high | Dossiê de handoff tem cobertura estreita | Investigator | Campos mínimos, evidência, limitações, tentativas e próximo passo. |
| high | Busca de knowledge sem resultado não aparece | Investigator | Zero resultado deve reformular ou limitar, nunca fabricar fonte. |
| high | Loop/stopping e tool redundante não aparecem | Investigator | Orçamento finito e chamadas repetidas com os mesmos argumentos. |
| high | Ambiguidade e múltiplas perguntas são estreitas | Understanding | Reformulações coloquiais, pergunta bloqueante e cobertura por questão. |
| medium | Contexto longo/ruidoso não aparece | Understanding + Investigator | Tickets longos com fatos irrelevantes e evidência contraditória. |
| low | Confirmation bias aparece em poucos padrões | Investigator | Mesma evidência com hipótese do usuário invertida. |

Os dados industriais existentes ajudam, mas não fecham essas lacunas sozinhos. Há 16 ativos não Golden: 13 com análises atuais saudáveis e três edges (`B211`, `C510`, `M428`) com baseline/qualidade/análise incompletos. Eles são úteis como sementes estruturais, não como respostas prontas.

## 6. What We Mean By Training

Neste projeto, “training” deve ser separado em cinco mecanismos:

1. **Deterministic programming**: schemas Pydantic, `extra="forbid"`, tenant checks, policy, budgets, Trace, Ledger e validações. Não se delega isso ao modelo.
2. **Prompting**: instruções, tool descriptions, formato de saída e poucos exemplos não Golden. É o baseline obrigatório.
3. **Retrieval/context**: evidência de tools e knowledge aplicável fornecida durante a execução; não é memorização de fatos industriais.
4. **Supervised fine-tuning (SFT)**: pares entrada/target para entendimento estruturado ou decisão do Investigator, somente se o baseline não atingir a rubrica.
5. **Evaluation**: synthetic dev/holdout e, por último, Golden oficial após freeze. Dados de avaliação nunca são treino.

Não se recomenda ensinar ao modelo contratos, autorização, isolamento ou idempotência por exemplos quando essas propriedades podem ser impostas deterministicamente.

## 7. Fine-tuning Candidate Analysis

| Componente | Label disponível | Custo/risco | Baseline antes de SFT | Recomendação |
|---|---|---|---|---|
| Understanding Agent | Intenções, perguntas, entidades, missing info e pedido de ação | Moderado; targets locais e verificáveis | Prompt + schema constrained + rubrica de cobertura | **FIRST_FINE_TUNING_CANDIDATE**, apenas se houver ganho medido. |
| Investigator Agent | Próxima decisão, tool/args, answerability, refs e handoff | Alto; labels dependem de state/policy e risco de imitar trajetória | Policy e executor determinísticos + prompt + simulador congelado | **SECOND**, após fechar decisões críticas. |
| Reporter | Claim/citação/limitação | Alto risco de otimizar estilo e esconder falha upstream | Template/renderer determinístico | **NOT_RECOMMENDED_NOW**. |
| Policy, Trace, Ledger, tool boundary | Não aplicável | Erro seria de segurança/auditoria | Código e testes | **NEVER_AS_MODEL_RESPONSIBILITY**. |

O Golden Set não deve ser usado para fine-tuning. Seus 17 casos são pequenos, reconhecíveis e altamente suscetíveis a memorização de trajetórias.

## 8. Recommended Training Order

1. Congelar schemas, reason codes, policy de ACTION, tenant rules e rubricas.
2. Medir Understanding prompt-only em synthetic dev/holdout.
3. Gerar e revisar piloto de 36 exemplos de Understanding; expandir até 360 apenas se necessário.
4. Opcionalmente fazer SFT do Understanding e congelar sua versão.
5. Implementar simulador determinístico de estados/evidências do Investigator.
6. Medir Investigator prompt-only, inclusive negativos e counterfactuals.
7. Gerar/revisar piloto de 60 exemplos; expandir até 600 e considerar SFT somente após policy/Human Gate.
8. Congelar modelo, prompt, tools, policy e código; então executar synthetic holdout e finalmente Golden.

## 9. Synthetic Dataset Architecture

Arquitetura lógica proposta:

```text
datasets/
  synthetic/
    understanding/{train,dev,holdout}.jsonl
    investigator/{train,dev,holdout}.jsonl
    manifests/
  eval/
    golden/  # offline, acesso restrito, nunca importado pelo runtime
```

Cada amostra tem versão de schema, split, input, target, tags e provenance. Assets, templates e `counterfactual_group` são disjuntos entre splits. O design não cria esse diretório nem o dataset nesta etapa.

Pools não Golden propostos:

- train: `H110`, `F115`, `C210`, `R310`, `M312`, `F520`, `P712`, `G715`, `F215`, `R610`;
- dev: `B211`, `S425`, `X216`;
- holdout: `C510`, `M428`, `M612`;
- eval: somente os dez assets Golden, nunca usados nos splits sintéticos.

Parquet/JSON existentes podem fornecer envelopes e combinações fisicamente plausíveis. Overlays sintéticos precisam ser explicitamente marcados e revisados; não devem modificar seeds oficiais nem ser apresentados como fatos reais.

## 10. Understanding Training Schema

O target contém `request_class`, intents, perguntas decompostas, entidades, alvos de investigação, informação ausente, ações solicitadas, restrições e confiança. `action_execution_allowed` é constante `false`: entender um pedido de ação não o autoriza.

Regras principais:

- output estritamente estruturado e sem cadeia de pensamento;
- uma entrada pode conter várias perguntas e entidades;
- missing information registra `blocking` e, quando útil, uma única pergunta sugerida;
- requested action registra intenção explícita e necessidade de evidência;
- provenance exige revisão anti-leakage.

O JSON companheiro contém o JSON Schema Draft 2020-12 completo e exatamente dois exemplos de formato, ambos com `"schema_example_only": true`. Eles não constituem dataset.

## 11. Investigator Training Schema

O input contém request estruturado, evidências correntes, tools disponíveis e execution state. Evidência separa `transport_ok` de `evidence_status`. O target admite apenas `TOOL_CALL`, `ASK_USER`, `ANSWER` ou `ESCALATE`; `ACTION` é deliberadamente excluída enquanto a policy futura não existir.

Regras principais:

- `TOOL_CALL` inclui somente nome e argumentos permitidos;
- `ASK_USER` identifica campos faltantes e formula pergunta mínima;
- `ANSWER` fornece specs de claims com `evidence_refs`, answerability e limitações;
- `ESCALATE` fornece reason codes, evidências, informação faltante e próximo passo;
- `remaining_tool_budget`, tenant validado e chamadas anteriores governam stopping;
- não há rationale livre nem chain-of-thought como label.

O JSON contém o schema completo e exatamente dois exemplos de formato marcados como schema-only: um primeiro tool call e um `ASK_USER` por asset ausente.

## 12. Negative Examples

O plano reserva exemplos explícitos para:

| Categoria | Comportamento-alvo | Quantidade recomendada |
|---|---|---:|
| Diagnóstico fabricado | limitar/buscar evidência | 80 |
| Resposta sem evidência | TOOL_CALL ou ASK_USER | 80 |
| ACTION proibida | reconhecer e encaminhar, nunca executar | 80 |
| Tool irrelevante | escolher a chamada que reduz incerteza | 70 |
| Cross-tenant | bloquear sem revelar existência/dados | 60 |
| Conflito tratado como conclusão | preservar conflito e desempatar/limitar | 60 |
| Unavailable tratado como complete | separar HTTP de semântica | 60 |
| Confirmation bias | seguir evidência contrária ao framing | 50 |
| Fonte de knowledge inventada | reformular ou declarar ausência | 50 |
| Loop de tool repetida | parar/mudar estratégia | 50 |

Essas quantidades são tags de cobertura que podem se sobrepor às 600 amostras do Investigator; não devem ser somadas como amostras adicionais.

## 13. Counterfactual Training

São recomendados 120 pares, sempre mantendo quase toda a entrada constante e mudando uma variável causal:

| Par | Pares | Delta esperado |
|---|---:|---|
| complete vs partial | 20 | answer versus próxima evidência/limitação |
| baseline established vs learning | 20 | confirmar desvio versus não confirmar |
| data quality boa vs ruim | 20 | confiança suportada versus cautela |
| permissão true vs false | 15 | proposta ao gate versus bloqueio; sem ACTION no target |
| mesmo tenant vs outro tenant | 15 | tool permitida versus bloqueio seguro |
| knowledge encontrado vs zero resultados | 10 | recuperar fonte versus reformular/limitar |
| análise current vs stale | 10 | usar versus atualizar evidência |
| banda crítica presente vs ausente | 10 | conclusão suportada versus inconclusiva |

O `counterfactual_group` inteiro permanece no mesmo split para evitar vazamento entre train e avaliação.

## 14. Dataset Size Recommendation

| Dataset | Train | Dev | Holdout | Total |
|---|---:|---:|---:|---:|
| Understanding | 240 | 60 | 60 | 360 |
| Investigator | 400 | 100 | 100 | 600 |
| Total sintético | 640 | 160 | 160 | 960 |

Understanding: 90 contextualize, 150 investigate, 80 reconhecimento de execute/handoff e 40 mixed/unclear; 126 easy, 162 medium e 72 hard.

Investigator: 330 TOOL_CALL, 90 ASK_USER, 120 ANSWER, 60 ESCALATE e 0 ACTION; 120 easy, 300 medium e 180 hard. Condição dominante: 120 complete/healthy, 80 partial, 70 inconclusive, 70 conflict, 60 unavailable semântico, 60 falha de transporte/HTTP, 50 missing/ambiguous, 50 tenant/permission e 40 stopping/redundancy.

Esses números são teto inicial, não meta cega. Primeiro deve ser gerado um piloto de 10%, revisado por rubrica e expandido apenas nas células com erro. Mais volume com labels inconsistentes pioraria o resultado.

## 15. Train vs Golden Coverage

| Competência | Golden | Sintético planejado | Separação semântica |
|---|---|---|---|
| Request understanding | média; pouca ambiguidade | 240 train / 60 holdout | novas formulações e entidades |
| Planning | alta em 17 trajetórias | 260 / 70 | ordens alternativas e estados novos |
| Evidence reasoning | alta nos cinco statuses | 300 / 80 | combinações e counterfactuals novos |
| Tool use | todas as 15 capabilities | 300 / 80 | sem copiar assinaturas de trajetória |
| Decision policy | answer/action/escalate; sem ask | 300 / 80 | inclui ASK_USER; exclui ACTION atual |
| Safety | permissão/justificativa parcial | 200 / 60 | tenant, retry e autoridade |
| Response grounding | narrativa forte, claim fraca | 160 / 50 | claim-evidence atômico |
| Human handoff | dois casos | 80 / 30 | dossiês e limites variados |
| Multi-question/asset | duas multi-question, zero multiasset | 120 / 40 | dois ou mais ativos e perguntas |
| Robustness | semântica e 400/403 | 200 / 60 | timeout, 5xx, loop, contexto longo |
| Action accountability | cinco ações, sem retry/idempotência | 80 / 30 | reconhecimento seguro, não execução |

Contagens por competência se sobrepõem. O objetivo é cobertura de habilidade, não reproduzir o Golden com outros nomes.

## 16. Anti-Leakage Policy

1. Mensagens, respostas, notas e expected paths oficiais não entram em treino, dev, holdout ou prompt de produção.
2. `expected-paths.json` nunca é importado por runtime, agente, gerador ou dataset loader.
3. IDs de tickets, casos, assets, analyses e knowledge do Golden são proibidos nos splits sintéticos.
4. Paráfrase que conserva entidades e assinatura causal/trajectory Golden é rejeitada, mesmo com baixa similaridade lexical.
5. Assets, templates e counterfactual groups são disjuntos entre train/dev/holdout.
6. Holdout sintético nunca é usado para tuning, seleção de exemplo ou threshold.
7. Golden só é executado após freeze de modelo, prompt, tools, policy e código.
8. Auditoria automática verifica IDs, n-grams, similaridade semântica e assinatura de trajetória.
9. Revisão humana decide casos limítrofes e pode rejeitar equivalência conceitual.
10. Artefatos Golden permanecem offline e fora do pacote de aplicação.

## 17. Risks

- **Memorização disfarçada:** templates sintéticos podem reproduzir a causalidade dos 17 casos mesmo sem copiar texto.
- **Policy drift:** treinar ACTION antes do Human Gate criaria autoridade inexistente e conflito com a Tool Layer atual.
- **Label inconsistency:** estados partial/conflict/unavailable admitem mais de uma próxima ação legítima; a rubrica deve aceitar equivalentes.
- **Simulator bias:** um gerador estreito ensina artefatos do simulador, não raciocínio industrial geral.
- **False realism:** overlays sintéticos tecnicamente incoerentes podem induzir diagnóstico errado.
- **Class imbalance:** excesso de tool calls pode ensinar investigação interminável; excesso de negativos pode ensinar abstenção excessiva.
- **Evaluation contamination:** usar resultados Golden para ajustar prompt, thresholds ou geração invalida a medição final.
- **Missing source documentation:** a ausência de `eval/README-eval.md` deixa parte do protocolo implícita.

Mitigações: piloto pequeno, revisão dupla, validação estrutural automatizada, testes counterfactuals, pools disjuntos, freeze versionado e execução Golden única ao final do ciclo de decisão.

## 18. Decisions Required Before Generation

Antes de gerar o dataset completo, é necessário:

1. Aprovar o Understanding como primeiro candidato e exigir baseline prompt-only.
2. Definir como avaliar pedidos de ACTION enquanto policy/Human Gate não existem; a recomendação atual é reconhecer/propor, nunca executar no target do Investigator.
3. Congelar schemas, reason codes e regras condicionais dos targets.
4. Aprovar os pools de assets e a política de overlays sintéticos.
5. Definir limiares automáticos e revisão humana anti-leakage.
6. Definir rubricas de label, equivalências aceitáveis e acordo entre anotadores.
7. Definir orçamento de tools e stopping policy do Investigator.
8. Definir armazenamento/acesso offline do Golden e registrar formalmente a ausência de `eval/README-eval.md`.

**Final status: READY_WITH_DECISIONS**
