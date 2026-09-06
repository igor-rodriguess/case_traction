# Revisão final de readiness — MVP Inteli × TRACTIAN

Auditoria determinística sobre o estado atual. Nenhuma rodada nova de benchmark foi executada; as únicas execuções externas foram build, lint e typecheck do frontend, todos locais.

## Veredicto

**`READY_TO_FINALIZE`** — zero BLOCKERS.

## Repositório

| Item | Estado |
|---|---|
| Commits da sequência 09 | 4, todos com árvore limpa |
| `.env` no histórico | **nunca versionado** |
| Segredos no histórico completo | **zero** |
| `experiments/` | ignorado |
| `.venv` rastreado hoje | zero arquivos |
| `.venv` no histórico antigo | presente em `60041c5` e `a985776` |

O `.venv` entrou em dois commits antigos e foi removido depois. Não há segredo envolvido: é peso de histórico. Reescrever o histórico é destrutivo e desproporcional agora. `KNOWN_LIMITATION`.

Frontend e `docs/frontend/` permanecem não rastreados e devem entrar em **commit separado**, por responsabilidade distinta.

## Testes

**421 passed · 0 failed · 0 skipped · 1 warning conhecido · ~6 s.** Sem rede.

`ACCEPTABLE_FOR_MVP`.

## Understanding

Acurácia 0,900 no split completo, contra 0,661 antes da calibração.

| Classe | n | Recall | Precisão |
|---|---:|---:|---:|
| `investigate` | 25 | 1,00 | 0,89 |
| `contextualize` | 15 | 0,93 | 1,00 |
| `execute` | 13 | 0,92 | 1,00 |
| `mixed` | 4 | 0,75 | 0,50 |
| `unclear` | 3 | **0,00** | — |

### Auditoria dos 3 casos `unclear`

Os três foram classificados como `investigate` (dois) e `mixed` (um). A causa é a definição do rótulo: o prompt define `unclear` como "desfecho vago **e** entidade apenas anafórica", mas essas mensagens trazem sintoma técnico concreto — "está estranho", "talvez seja tendência radial" — e o modelo lê isso como investigação. A definição é defensável dos dois lados.

**O erro não produz decisão insegura.** Nos três casos: a entidade ausente foi corretamente identificada como `asset_id` bloqueante; nenhuma entidade foi inventada; `action_execution_allowed` permaneceu `false`; e todos terminaram em `AWAITING_REQUIRED_INFORMATION` — exatamente o desfecho que `unclear` deveria produzir.

A Completion Policy absorve o erro de rótulo por completo: o comportamento observável é idêntico ao correto. Corrigir exigiria estreitar a fronteira `unclear`/`investigate`, com risco de regredir os 25 casos `investigate` hoje em recall 1,00.

`KNOWN_LIMITATION` — 3 casos de 60, sem efeito no fluxo.

## Grounding

`build_grounded_conclusion` materializa fatos de **2 das 10 READ tools**.

| Tool | EvidenceRecord | Materializa claim |
|---|---|---|
| `get_asset_context` | sim | **sim** |
| `get_analysis_details` | sim | **sim** |
| `list_asset_analyses` | sim | não |
| `get_asset_baseline` | sim | não |
| `get_asset_rms` | sim | não |
| `get_asset_spectrum` | sim | não |
| `get_asset_data_quality` | sim | não |
| `get_model_capabilities` | sim | não |
| `search_industrial_knowledge` | sim | não |
| `get_knowledge_document` | sim | não |

Não é bug: é **ausência de mapper**, e a ausência é em parte deliberada. As duas tools suportadas devolvem registros cadastrais com campos fixos e semântica estável, que viram enunciado factual sem interpretação. As demais devolvem série temporal, espectro, texto de conhecimento ou envelope de lista — materializá-las exigiria decidir *o que a medição significa*, que é justamente o julgamento diagnóstico que a arquitetura recusa fazer sem revisão humana.

Custo observado: 3 casos em que o Investigator respondeu com evidência boa e a conclusão não pôde ser expressa. O sistema falhou de forma segura, sem publicar nada.

Ampliar para `list_asset_analyses` e `get_asset_data_quality` é plausível — ambas têm payload de campos discretos. Fica como evolução, não como fix de hoje: mexer no grounding sem uma rodada de validação depois é pior que a limitação.

`KNOWN_LIMITATION`.

## Reporter

Auditado o único caso real de `UNSUPPORTED_CLAIM` (`syn_u_dev_0044`).

**O Reporter não inventou fato.** Ele preservou os dois `claim_id`, preservou 100% das `evidence_references`, e apenas **perdeu os acentos** do enunciado: "O ativo asset_S425 é Spindle secundário" virou "...e Spindle secundario".

A validação comparava por igualdade exata e rotulava isso como `UNSUPPORTED_CLAIM` — termo que sugere fabricação onde houve reescrita.

**Corrigido nesta revisão, sem relaxar a validação.** A violação passou a distinguir:

- `UNSUPPORTED_CLAIM` — `claim_id` ausente da conclusão: invenção de fato;
- `CLAIM_TEXT_ALTERED` — `claim_id` conhecido com texto reescrito: infidelidade.

O relatório continua **rejeitado** nos dois casos. O sistema segue preferindo recusar a publicar claim sem suporte. Dois testes cobrem a distinção.

`SHOULD_FIX` → corrigido nesta etapa.

## Trace e Evidence Ledger

Verificação sobre **162 runs de todos os experimentos**:

| Invariante | Resultado |
|---|---:|
| EvidenceRecords | 196 |
| Órfãos, sem `tool_completed` correspondente | **0** |
| Sem `source_call_id` | **0** |
| `trace_id` inconsistente | **0** |
| ACTION, tool ou decisão | **0** |
| Chain-of-thought persistido | **0** |

`ACCEPTABLE_FOR_MVP`.

## Estados terminais

Os quatro permanecem semanticamente separados. Confirmado nos artefatos:

- evidência insuficiente **nunca** virou ANSWER inventado — a Completion Policy converte em escalada;
- pedido temporal sem suporte **não fabricou parâmetro** — zero argumentos temporais inválidos na V2 e V2b, contra 3 na V1;
- erro de provider **não conta** como erro cognitivo — `behavioral_failure_rate` e `provider_failure_count` são métricas distintas.

## Frontend

| Verificação | Resultado |
|---|---|
| `tsc --noEmit` | **PASS** |
| `oxlint` | **PASS** |
| `vinext build` | **PASS** |
| Estados de loading e error | `loading.tsx` e `error.tsx` presentes |
| Seções | Trace, Evidence ledger, Human review, Grounded, Awaiting information |
| Artefatos de build | cobertos pelo `.gitignore` do frontend |

Os mocks usam os nomes de campo reais do backend — `evidence_id`, `source_call_id`, `trace_id`, `evidence_status`, `call_id`, `sequence`, `tool_name`, `claim_id`, `supporting_evidence_ids` — e os quatro estados terminais canônicos.

**`READY_WITH_MOCK_DATA`.** É página única com seções, não navegação multi-rota, e não há integração viva com a API.

## Escopo do MVP

**Faz parte:** Understanding, Planner, Investigator, Tool Executor determinístico, 10 READ tools, Execution Trace, Evidence Ledger, Completion Policy, Temporal Policy, grounding com lineage, Reporter com validação de fidelidade, semântica de revisão humana, dashboard com dados mockados tipados.

**Não faz parte:** execução de ACTION, fila e worker de produção, fallback de provider production-grade, fine-tuning, filtro temporal completo, alinhamento total do dataset, autenticação e isolamento de tenant, persistência em banco, Judges e Eval automatizado.

## Judges e Eval

Não há menção a Judges ou LLM-as-a-Judge nos requisitos do repositório (`README.md`, `STUDENT-GUIDE.md`, `docs/`). A avaliação determinística implementada — métricas por componente, quality gates com limiares declarados antes da rodada e taxonomia de camada responsável — cobre a necessidade de medição sem introduzir um avaliador probabilístico.

`POST_MVP`.

## Holdout e Golden

- DEV: usado para desenvolvimento, 60/60 coberto em duas coortes.
- HOLDOUT: **limpo**, nunca acessado.
- Golden Set: **limpo**, nunca acessado. O loader recusa splits fora da allowlist antes de qualquer I/O.

Nenhum requisito do repositório exige rodar Golden ou Holdout formalmente. Fica registrado como validação futura recomendada, a ser feita **uma única vez**, depois de qualquer calibração.

## Segurança

| Verificação | Resultado |
|---|---|
| Segredos no Git | **0** |
| Execução de ACTION | **0** |
| Headers arbitrários | não há; `RequestContext` é fixado pela aplicação |
| Identidade arbitrária vinda do LLM | impossível por contrato |
| `eval/expected-paths.json` em runtime | **nunca** |
| TRAIN, HOLDOUT ou Golden em prompt | **nunca** |

O guard de leakage prova por inspeção de código que `run_case` só toca a amostra por `sample_id`, `training_tags` e `runtime_payload(sample)`.

## Limitações conhecidas

1. `unclear` com recall 0,00 — 3 casos, sem efeito no comportamento observável.
2. Grounding materializa 2 das 10 READ tools.
3. Cobertura do dataset: 0 dos 60 casos totalmente alinhados com a API; nenhum descritor corroborado.
4. Nenhuma READ aceita recorte temporal, enquanto 52 dos 60 casos o pedem.
5. Frontend com dados mockados, sem integração viva.
6. `.venv` presente em dois commits antigos do histórico.
7. Latência dependente do Gemini, que apresentou HTTP 503 e picos acima de 90 s.

## Blockers

Nenhum.
