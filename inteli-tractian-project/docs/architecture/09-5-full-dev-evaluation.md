# Etapa 09.5 — Avaliação do Synthetic DEV completo

## Configuração congelada

O experimento `e2e-full-dev-v1` fixou routing, modelos, prompts, schemas, Completion Policy, grounding, superfície de tools e limites antes da primeira chamada. O manifesto guarda o digest SHA-256 de cada system prompt, de modo que qualquer alteração posterior seja detectável e não silenciosa.

| Item | Valor |
|---|---|
| routing | `MODEL_ROUTING_V4` |
| Understanding | Groq `openai/gpt-oss-120b`, `understanding_prompt_v2` |
| Planner / Investigator / Reporter | Gemini `gemini-3.5-flash-lite` |
| prompts | `e2e_planner_v1`, `e2e_investigator_v4`, `e2e_reporter_grounded_v1` |
| schema | `InvestigationDecision-1.0` |
| Completion Policy | `completion_policy_v1_09_4C`, inalterada |
| grounding | `grounding_v1_09_4F`, inalterado |
| recuperação | `one_llm_repair_then_deterministic_safe_escalation` |
| limites | 12 passos de investigação, 8 tool calls, `temperature=0.0` |
| retry de provider | 1 tentativa; throttle de 20 s entre casos |
| tools | 10 READs; nenhuma ACTION exposta |

Nada foi alterado durante a rodada. Os defeitos observados estão registrados e classificados, não corrigidos no meio do experimento.

## Split e validação determinística

O split DEV possui **60 casos reais** — a quantidade foi lida do arquivo, não presumida. Antes de qualquer chamada LLM, cada linha foi revalidada e o laudo persistido em `dataset-validation.json`: 60 amostras, 60 `sample_id` únicos, 0 duplicações, 0 falhas de schema, split correto em todas, nenhuma referência a artefato do Golden Set e proveniência declarando pool não-golden em todas.

O `target` de cada amostra existe no dataset e é usado apenas na pontuação offline do Understanding. A única projeção que alcança um provider é `runtime_payload()`, que devolve `UnderstandingInput` — `message` e `available_context`. A garantia é estrutural, não disciplinar: o runner nunca recebe a amostra inteira.

`TRAIN`, `HOLDOUT` e Golden Set não foram lidos. O loader recusa splits fora da allowlist antes de qualquer I/O.

## Cobertura de dados

A Etapa 09.4F havia observado qualitativamente que textos do DEV não correspondiam ao cadastro. A auditoria determinística (`data-coverage.json`) mediu a extensão, comparando cada menção a ativo com o registro que a própria API devolve.

O léxico substantivo→tipo de máquina é derivado do catálogo alcançável pela API — as três empresas dos ativos citados — e não de vocabulário inventado. Cadastro e evidência são lidos separadamente: o cadastro com seed fixa, por ser metadado, e a evidência sem seed, no mesmo regime da rodada avaliada.

| Medida | Valor |
|---|---:|
| Menções corroboradas pelo cadastro | **0** |
| Menções contraditas | 26 |
| Menções não verificáveis contra o catálogo alcançável | 24 |
| Menções sem descritor | 3 |
| Casos totalmente alinhados | **0** / 60 |
| Casos parcialmente alinhados | 24 / 60 |
| Casos desalinhados | 26 / 60 |
| Casos sem entidade resolvível | 10 / 60 |
| Casos com conclusão factual estruturalmente alcançável | 37 / 60 |
| Casos pedindo recorte temporal inexistente na superfície de tools | 52 / 60 |

Nenhum descritor do DEV corresponde ao ativo que nomeia. `asset_S425` é "Spindle secundário" e aparece como compressor, bomba e exaustor; `asset_X216` é "Misturador de cru" e aparece como spindle, refiner e ventilador. Os descritores foram gerados por um pool independente dos identificadores.

Três fatores adicionais, todos da camada de dados:

1. `asset_B211` retorna `get_asset` em modo `inconclusive` de forma determinística. Os casos que citam apenas B211 não têm conclusão factual alcançável, independentemente do comportamento do agente.
2. Nenhuma das 10 READs aceita recorte temporal, enquanto 52 casos pedem "desde o último turno", "após a limpeza" ou equivalente.
3. Dez casos referenciam o ativo apenas por anáfora — "aquele misturador que comentamos", "o equipamento reserva" — sem identificador e com `asset_refs` vazio.

As 26 contradições são um **piso, não o total**. O catálogo alcançável cobre 7 substantivos; "redutor", "refiner", "transportador" e "exaustor" permaneceram `UNVERIFIABLE` em vez de presumidos errados, o que subestima deliberadamente o desalinhamento.

## Limite de interpretação de `grounded_answer_reachable`

A métrica é **estrutural**: indica que um fato de cadastro poderia ser materializado por `build_grounded_conclusion`, não que a pergunta do usuário poderia ser respondida. As perguntas do DEV são majoritariamente do tipo "o que significa X para o ativo Y" e "a tendência mudou desde o último turno"; responder pelo cadastro não responderia nenhuma delas.

Portanto `grounded_completion_rate_when_reachable` não deve ser lida como taxa de erro do Investigator. O limiar do gate foi declarado em código antes da rodada e não foi ajustado após ver os resultados; a interpretação fica aqui, e os casos afetados entram na lista de revisão humana.

## Execução

Os 60 casos rodaram sequencialmente, com throttle de 20 s, contra a API local. A rodada durou 653 s de latência agregada de provider e não foi interrompida.

| Terminalidade | Casos | Taxa |
|---|---:|---:|
| `AWAITING_REQUIRED_INFORMATION` | 29 | 48,3% |
| `SAFE_ESCALATION` | 24 | 40,0% |
| `FAILED` | 7 | 11,7% |
| `GROUNDED_COMPLETION` | **0** | 0% |

`valid_terminal_state_rate` = 88,3%. Dead ends = 0, escaladas por falha de contrato = 0, transições de estado quebradas = 0.

Custo: 243 chamadas LLM (4,05 por caso), 462.281 tokens (7.705 por caso), 65 tool calls (1,08 por caso). Latência E2E média 10.877 ms, P50 7.469 ms, P95 26.281 ms. Groq 60 chamadas / 226.280 tokens; Gemini 183 chamadas / 236.001 tokens.

## Por que os sete casos falharam

Nenhuma falha veio do grafo. A decomposição por `finish_reason` aponta orçamento de saída:

| Causa | Casos | Evidência |
|---|---:|---|
| Planner truncado no teto do provider | 4 | `finish=MAX_TOKENS` a 495–498 tokens |
| Understanding truncado | 1 | `finish=length` |
| 5xx transitório sem retry | 1 | `http_status` |
| Violação de schema genuína do Planner | 1 | `finish=STOP` a 302 tokens |

A causa raiz das quatro primeiras é um defeito de configuração: `ProviderConfig.max_output_tokens` tem default 512 e a entrada do Gemini nunca o sobrescrevia, ao contrário da entrada do Groq, que declara 2048. Como o adapter aplica `min(request, config)`, todos os papéis roteados ao Gemini eram silenciosamente cortados em 512 — Planner pedia 900, Investigator 700 e Reporter 1200. O Investigator sobreviveu porque `InvestigationDecision` é um objeto pequeno; o Planner, não.

O corte chegava às camadas superiores disfarçado de erro de schema, o que fazia o diagnóstico apontar para o prompt. A correção pós-rodada declara o teto real do Gemini, detecta `finish_reason` de corte e devolve `output_truncated` na camada `configuration`, além de habilitar uma segunda tentativa para 5xx transitório. Nada disso foi aplicado durante a rodada.

## Componentes

**Understanding** — schema válido em 98,3%. `request_class_accuracy` de 66,1% **rejeita a hipótese `NO_TRAINING_NEEDED`** herdada das etapas anteriores. A precisão é fortemente desigual: `investigate` 100%, `contextualize` 93,3%, e **`execute` 0%** — os 13 casos de execução foram classificados como `mixed`. `unclear` também zerou. Identificadores inventados: 0. Violações de `action_execution_allowed`: 0.

**Planner** — schema válido em 91,5%, 204 capabilities sugeridas, 79,4% estruturalmente aplicáveis e 29,9% efetivamente executadas. Adequação semântica do objetivo permanece `NEEDS_HUMAN_REVIEW`: não há alvo determinístico para plano neste split.

**Investigator** — 117 decisões registradas, 94,0% válidas na primeira passagem, 6,0% com repair e **0% de falha após repair**. Tool inválida 0%, ACTION 0, loop 0%, repetição bloqueada pela política em 3,4%. Os 7 argumentos inválidos são informativos: os campos rejeitados foram `time_window`, `hours`, `window`, `mode`, `analysis_id` e `doc_id`. O Investigator inventou parâmetros temporais que a superfície de tools não possui — é o gap temporal dos dados reaparecendo como violação de contrato, e o schema o barrou corretamente.

**Reporter** — não alcançado em nenhum caso, por regra e não por falha: exige `InvestigationConclusion` válida, que exige `ANSWER` aceito, que não ocorreu.

## Evidência

65 EvidenceRecords, todos com `source_call_id` correspondente a um `tool_completed` do próprio Trace — 0 evidências órfãs. Distribuição semântica: 37 `complete`, 10 `inconclusive`, 8 `partial`, 6 `unavailable`, 4 `conflict`. Nenhum status foi reclassificado.

Tools usadas: `get_asset_context` 25, `search_industrial_knowledge` 13, `list_asset_analyses` 8, `get_asset_data_quality` 7, `get_asset_spectrum` 4, `get_asset_rms` 4, `get_asset_baseline` 4.

Claims, lineage e conclusões: 0. A integridade do grounding não foi exercitada nesta rodada.

## Por que nenhuma conclusão grounded

O exame caso a caso mostra escaladas individualmente justificadas, não desistência arbitrária. Três padrões representativos:

- `0003` obteve cadastro `complete` e depois conhecimento industrial em `conflict`; escalou com `CONFLICTING_EVIDENCE`. A Completion Policy bloquearia um `ANSWER` citando aquela evidência.
- `0015` obteve cadastro `complete` e análises `unavailable`; a política converteu uma repetição de tool em escalada segura.
- `0011` pediu `ask_user` com `MISSING_TIME_WINDOW`, solicitando o intervalo temporal — exatamente o gap que a auditoria previu em 52 casos.

A correlação com cobertura é direta: os 10 casos `IMPOSSIBLE_FROM_API` terminaram em 7 `ask_user` e 3 falhas; nenhum caso `FULLY_ALIGNED` existiu para ser concluído.

## Limitações da rodada

1. **Perda de registro por caso abortado.** `components["investigator"]` só era publicado após o laço, então os 7 casos abortados perderam o bloco. Como 6 falharam antes de qualquer decisão, a perda real foi de **1 decisão em 118 (0,85%)**. O Trace preserva o ciclo completo e `state.decision` preserva a decisão íntegra. Corrigido após a rodada, sem retroagir no artefato.

2. **`provider_error_rate` subestimado.** A métrica lê os registros por tentativa; como o caso `0008` perdeu os seus, o 5xx observado não é contado e o gate `PROVIDER_STABILITY` mostra 0 erros. O valor correto é 1 erro em 244 chamadas.

3. **Contradições de descritor são um piso.** O léxico cobre 7 substantivos do catálogo alcançável; "redutor", "refiner", "transportador" e "exaustor" ficaram `UNVERIFIABLE`.

## Quality gates

| Dimensão | Veredicto | Observado |
|---|---|---|
| ARCHITECTURE_STABILITY | **FAIL** | terminal válido 88,3%; dead end 0; erro estrutural 0 |
| CONTRACT_RELIABILITY | PASS_WITH_WARNINGS | primeira passagem 94,0%; falha após repair 0%; ACTION 0 |
| INVESTIGATION_QUALITY | **FAIL** | grounded quando alcançável 0%; loop 0% |
| GROUNDING_QUALITY | PASS_WITH_WARNINGS | 0 claims: não exercitado |
| REPORTER_QUALITY | PASS_WITH_WARNINGS | 0 alcançados: bloqueado por regra |
| DATA_COVERAGE | **FAIL** | 0 alinhados, 26 desalinhados, 10 impossíveis |
| PROVIDER_STABILITY | PASS | 0 erros contabilizados (ver limitação 2) |

`ARCHITECTURE_STABILITY` reprova por `valid_terminal_state_rate` abaixo de 95%. O gate está correto ao disparar, mas a causa apurada é o defeito de orçamento de saída, já localizado e corrigido — não uma falha estrutural do grafo, cujos indicadores diretos (dead end, transição de estado, ACTION) estão todos zerados.

Status: **`FIX_ARCHITECTURE_BEFORE_TRAINING`**.

## Revisão humana

50 casos entraram na fila prioritária, por três motivos que nenhuma regra decide:

- `PLAN_PRODUCED_WITHOUT_ANY_TOOL_EXECUTION` (31) — plano produzido sem nenhuma READ executada.
- `ESCALATION_DESPITE_REACHABLE_GROUNDED_ANSWER` (17) — escalada onde um fato de cadastro era materializável. Ver a ressalva sobre a métrica ser estrutural.
- `ASK_USER_DESPITE_RESOLVABLE_ENTITY` (17) — pergunta ao usuário com entidade resolvível disponível.

## Artefatos

Brutos em `experiments/e2e-full-dev-v1/` (fora do versionamento): `manifest.json`, `runs.jsonl`, `aggregate-metrics.json`, `component-metrics.jsonl`, `errors.jsonl`, `dataset-validation.json`, `data-coverage.json`, `quality-gates.json`, `needs-human-review.json`, `showcase.json`, `checkpoint.json`.

Showcase curado e versionado em `docs/architecture/examples/09-5-full-dev-showcase.json`, gerado por `scripts/generate_full_dev_showcase_example.py`. Sete casos únicos cobrindo escalada segura, espera por informação, os cinco estados semânticos de evidência, desalinhamento de descritor e erro real. `grounded_completion` consta explicitamente como categoria ausente.

Nenhum micro-piloto anterior foi sobrescrito.

## Segurança

ACTION propostas: 0. ACTION executadas: 0. Identificadores inventados: 0. Segredos em artefato: nenhum. `TRAIN`, `HOLDOUT` e Golden Set: não acessados.
