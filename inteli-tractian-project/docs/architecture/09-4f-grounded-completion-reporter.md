# Etapa 09.4F — Grounded Completion e Reporter

## Auditoria determinística

O Synthetic DEV foi inspecionado apenas pelos inputs autorizados. Seus casos referenciam `asset_B211`, `asset_S425` e `asset_X216`. A API possui dados não vazios para os três: cadastro, baseline, 30 amostras RMS, espectro e qualidade; S425 e X216 também possuem análise atual saudável.

Nenhum caso DEV foi selecionado para conclusão positiva. Os nomes e contextos textuais não são coerentes com o cadastro: `asset_S425` é “Spindle secundário”, mas aparece no DEV como exaustor, bomba, compressor ou motor; `asset_X216` é “Misturador de cru”, mas aparece como spindle, refiner ou transportador. A API também não representa necessariamente o contexto operacional temporal pedido. Forçar uma resposta misturaria entidades ou inferiria contexto ausente.

Foi criada uma única `INTEGRATION_FIXTURE`, sem expected answer e sem valor de benchmark. Critérios: asset identificável, cadastro existente, payload não vazio, uma READ aplicável e campos factuais diretamente materializáveis. A pergunta solicita nome, tipo, criticidade e status do sensor de `asset_S425`. O proxy de integração fixa `seed=complete`; esse seed não fica disponível ao LLM.

## Alterações

- `TraceEvent` passou a representar eventos operacionais de decisão, validação, aceite/rejeição, tool request, conclusão e Reporter, sem chain-of-thought.
- Cada nova run possui `started_at`, `finished_at` e `duration_ms` derivada.
- `build_grounded_conclusion` materializa claims somente a partir de campos presentes em EvidenceRecords elegíveis.
- `build_claim_lineage` valida Claim → EvidenceRecord → call_id/sequence → `tool_completed` → READ/path.
- `validate_reporter_output` mede preservação de claims, evidence refs, limitações, unresolved points e audience, e detecta claims adicionais.
- Completion Policy e prompt `e2e_investigator_v4` não foram alterados.

## Testes e smoke

O smoke offline validou `ANSWER → InvestigationConclusion → ReporterOutput`, lineage, rejeição de claim inventada, rejeição de limitação omitida, evento de decisão, metadados obrigatórios de tool e timestamps. Regressão final: 323 passed, 0 failed, 0 skipped, 1 warning conhecido, 3,95 s.

## Micro-piloto real

O experimento `e2e-grounded-pilot-v1` executou uma única fixture:

1. Understanding/Groq produziu contrato válido, embora tenha classificado o lookup READ como `execute`; `requested_actions=[]` e `action_execution_allowed=false` preservaram segurança.
2. Planner/Gemini sugeriu lookup read-only.
3. Investigator/Gemini produziu `tool_call(get_asset_context)` válido.
4. A API retornou EvidenceRecord `complete` com o cadastro real de S425.
5. Investigator produziu `answer`, citando exatamente o evidence ID; Completion Policy respondeu `GROUNDED_ANSWER_ALLOWED`.
6. A conclusão determinística criou uma claim factual supported.
7. A lineage foi válida.
8. Reporter/Gemini preservou integralmente claim e evidence ID e entregou audience `tractian_engineering_team`.

Resultado: 1 grounded completion, 0 dead ends, 0 repairs, 0 errors, 1 READ, 1 EvidenceRecord, 2 decisões e 12 eventos de Trace. A run durou 7.909,558 ms. Foram 5 chamadas LLM, 7.656 tokens e 7.612,546 ms de latência agregada de provider.

Reporter: schema 100%, claim preservation 100%, evidence-reference preservation 100%, unsupported claims 0%, target correto. Como a conclusão não possuía limitações ou unresolved points, suas taxas de preservação são verdadeiras por conjunto vazio; o teste offline adicional comprova rejeição quando uma limitação existente é omitida.

## Observações

O artefato V1 preserva o reason code `GROUNDED_ANALYSIS_EVIDENCE`, rótulo legado impreciso para cadastro. Após a rodada, o código futuro foi corrigido para `GROUNDED_READ_EVIDENCE`; o experimento não foi alterado nem reexecutado.

O comportamento conservador da V4 foi `CORRECT_SAFE_BEHAVIOR` diante dos cinco casos anteriores. O bloqueio positivo era principalmente `DATA_COVERAGE_GAP`/alinhamento entre DEV e API, não defeito comprovado do Investigator, Planner ou Completion Policy.

Status: `PROCEED_TO_FULL_DEV`, sem iniciar automaticamente os 60 casos.
