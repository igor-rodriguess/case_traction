# 01 — API and Domain Audit

Audit date: 2026-08-29
Scope: documentation, static OpenAPI contracts, FastAPI implementation, data access, probabilistic behavior, tests, support cases, scenarios, and evaluation paths.
Decision boundary: this document records current behavior. It does not correct the API, create tools, or begin Step 02.

## 1. Executive Summary

The repository exposes **18 operations**: **13 READ** and **5 ACTION**, across company/user/asset context, analyses, technical data, models, knowledge, and support actions. The two distributed static contracts are byte-identical. The FastAPI implementation defines the same conceptual operation set, but the contracts are not safe to use as a generated client/tool source without normalization.

The most consequential findings are:

1. The YAML repeats the mapping key `/assets/{assetId}`. YAML parsers commonly keep only the last key, so the GET or PATCH can disappear depending on parser behavior.
2. The static contract applies `UserContext` globally, while runtime allows all reads except `/users/me` without a header.
3. `x-user-id` is an unsigned, caller-controlled identity, and runtime performs no company/asset/case ownership checks.
4. ACTION endpoints validate permission and justification but do not validate action-specific fields and do not persist any state. “Accepted” is a simulated acknowledgement.
5. Runtime GET payloads are untyped in FastAPI and several differ structurally from static schemas, particularly `Asset`.
6. Probabilistic reads always return HTTP 200 for partial, inconclusive, conflict, and unavailable outcomes; consumers must inspect `mode`, `notes`, and payload shape.

Static audit totals:

| Measure | Result |
|---|---:|
| Operations | 18 |
| READ operations | 13 |
| ACTION operations | 5 |
| Contract/runtime finding groups | 12 |
| Support tickets | 17 |
| Evaluation scenarios | 16 |
| Candidate tools | 18 |
| Existing tests discovered | 39 |

Runtime execution was attempted but could not be performed because `python`, `py`, `python3`, and `uv` are unavailable in the environment PATH. Consequently, `/openapi.json` and pytest results could not be generated. The runtime observations below are static deductions from FastAPI decorators, signatures, models, and handlers and are labeled as such.

## 2. Domain Map

The core relationship is:

```text
Company ── has ──> Users
   │
   └── has ──> Assets ── has ──> Measurement Points
                    │
                    ├── Analyses ── produced by ──> Model
                    ├── Baseline
                    ├── RMS series
                    ├── Spectrum
                    └── Data quality

Support Case ── references ──> Company + User + Asset
Knowledge ── supports ──> explanation and investigation
Actions ── target ──> Asset | Analysis | Model | Support Case
```

Key domain rules confirmed across the guide, schemas, seed data, scenarios, and code:

- Baseline lifecycle is `learning → established → invalidated`.
- RMS alarm threshold is computed from the asset baseline as `reference + tolerance`; it is not a fixed ISO/class table.
- Baseline detection requires a usable learned reference. Symptom detection, notably lubrication, may be valid while baseline is `learning` and `learnable=false`.
- Analysis evidence must be interpreted with its `confidence`, `limitations`, `baseline_state_at_detection`, current baseline, data quality, and model requirements.
- `pending`, `stale`, and `inconclusive` are analysis data states; they are distinct from probabilistic envelope modes.
- A support response can orient, investigate, act, or escalate. Only the last two should invoke ACTION operations.

Data is loaded from parquet into a cached in-memory store. All lookups are by supplied IDs. There is no relationship authorization layer after lookup.

## 3. Endpoint Inventory

The canonical machine-readable detail is in [`01-endpoint-inventory.json`](./01-endpoint-inventory.json). This table summarizes the audit.

| # | Method and path | Category | Inputs | Principal response | Permission | Errors | Cases |
|---:|---|---|---|---|---|---|---|
| 1 | `GET /companies/{company_id}` | CONTEXTO | path ID; `seed` | envelope + company | runtime anonymous | 404 | context discovery |
| 2 | `GET /companies/{company_id}/assets` | CONTEXTO | path ID; `seed` | envelope + asset list | runtime anonymous | 404 | context discovery |
| 3 | `GET /users/me` | CONTEXTO | `x-user-id` | unwrapped user/permissions | known user | 401 | action preflight |
| 4 | `GET /assets/{asset_id}` | CONTEXTO | path ID; `seed` | envelope + flat asset + points | runtime anonymous | 404 | CTX-01, INV-04/07/11, EXE-13/14 |
| 5 | `PATCH /assets/{asset_id}` | AÇÃO | path ID; header; body | `ActionResult` | `action_high` | 400/401/403/404/422 | EXE-14 |
| 6 | `GET /assets/{asset_id}/analyses` | INVESTIGAÇÃO | path ID; `status`; `seed` | envelope + list | runtime anonymous | 404 | CTX-02, INV-04/05/08, EXE-13/15 |
| 7 | `GET /analyses/{analysis_id}` | INVESTIGAÇÃO | path ID; `seed` | envelope + evidence | runtime anonymous | 404 | most diagnostic/action cases |
| 8 | `POST /analyses/{analysis_id}/reprocess` | AÇÃO | path ID; header; body | `ActionResult` | `action_low` | 400/401/403/404/422 | INV-09, EXE-12 |
| 9 | `POST /analyses/{analysis_id}/request-specialist` | AÇÃO | path ID; header; body | `ActionResult` | `action_low` | 400/401/403/404/422 | EXE-13 |
| 10 | `GET /assets/{asset_id}/baseline` | INVESTIGAÇÃO | path ID; `point_id`; `seed` | envelope + baseline | runtime anonymous | 404 | 11 tickets |
| 11 | `GET /assets/{asset_id}/rms` | INVESTIGAÇÃO | path ID; `point_id`; `seed` | envelope + RMS/threshold | runtime anonymous | 404 | CTX-03, INV-04/05/07/09, EXE-12 |
| 12 | `GET /assets/{asset_id}/spectrum` | INVESTIGAÇÃO | path ID; `point_id`; `seed` | envelope + peaks/bands | runtime anonymous | 404 | CTX-02, INV-06/07/08/10/11b |
| 13 | `GET /assets/{asset_id}/data-quality` | INVESTIGAÇÃO | path ID; runtime `point_id`; `seed` | envelope + quality | runtime anonymous | 404 | CTX-03, INV-04/05/09/10 |
| 14 | `GET /models/{model_id}` | INVESTIGAÇÃO | path ID; `seed` | envelope + capabilities | runtime anonymous | 404 | INV-04/05/06/09/10/11, EXE-15 |
| 15 | `POST /models/{model_id}/request-retraining` | AÇÃO | path ID; header; body | `ActionResult` | `action_high` | 400/401/403/404/422 | EXE-15 |
| 16 | `GET /knowledge/search` | INVESTIGAÇÃO | required `q`; `type`; `seed` | envelope + results | runtime anonymous | 422 if no `q` | CTX-01/02/03, INV-07/08/11b |
| 17 | `GET /knowledge/{doc_id}` | INVESTIGAÇÃO | path ID; `seed` | envelope + document | runtime anonymous | 404 | CTX-01/02/03 |
| 18 | `POST /cases/{case_id}/escalate` | AÇÃO | path ID; header; body | `ActionResult` | `escalate` | 400/401/403/404/422 | INV-04, EXE-16 |

Important response details:

- GET operations except `/users/me` return `{mode, notes, data}`.
- A missing baseline, spectrum, or data-quality record is HTTP 200 with `mode=inconclusive` and a resource-specific null wrapper, not 404.
- An unavailable probabilistic result is generally HTTP 200 with `data={}`.
- Stable categories (`knowledge`, `company`, and plural `assets`) retain payloads for inconclusive/unavailable modes. However, single-asset lookup uses category `asset`, so it is not treated as stable.
- Search returns full matching documents, not lightweight result references.

## 4. READ vs ACTION Operations

### READ (13)

All GETs are read-only at the store level. They include four CONTEXTO operations and nine INVESTIGAÇÃO operations. They can vary probabilistically except `/users/me`, which is returned directly.

READ consumers must distinguish:

- transport success (`HTTP 200`);
- evidence availability (`mode`);
- semantic state inside the data (`pending`, `stale`, baseline lifecycle, model processing);
- missing records represented as either 404 or a 200/inconclusive null, depending on resource.

### ACTION (5)

| Operation | Required permission | Justification | Declared effect | Actual implementation effect |
|---|---|---|---|---|
| Update asset config | `action_high` | ≥20 trimmed chars | update criticality/config | returns acceptance only |
| Reprocess analysis | `action_low` | ≥20 trimmed chars | reprocess | returns acceptance only |
| Request specialist | `action_low` | ≥20 trimmed chars | create specialist request | returns acceptance only |
| Request retraining | `action_high` | ≥20 trimmed chars | create retraining request | returns acceptance only |
| Escalate case | `escalate` | ≥20 trimmed chars | create human handoff | returns acceptance only |

No action-specific parameters are enforced. For example, PATCH accepts a valid justification even when `changes` is absent or contains an unsupported criticality. The asset row is not modified, so the expected post-PATCH validation GET in CEN-15 cannot observe the requested state.

## 5. Authentication and Permission Findings

### Current identity flow

- Caller supplies `x-user-id`.
- Runtime loads that exact ID from `users.parquet`.
- `/users/me` rejects a missing or unknown ID.
- ACTION dependencies reject missing/unknown users and require one literal permission.
- Other GETs do not resolve a user at all.

Permission matrix:

| Permission | Operations |
|---|---|
| `read` | Present in user data but not checked on GETs |
| `action_low` | reprocess, request specialist |
| `action_high` | update asset, request retraining |
| `escalate` | escalate case |

### Trust boundary for a future application

Must come from trusted application/session context:

- authenticated `user_id` and effective permissions;
- `company_id`/tenant membership;
- authoritative `case_id` and the case’s company/user/asset relationship;
- authorization decision, confirmation state, and action policy;
- trace/run identity and idempotency key.

May be proposed by an agent but must be validated against trusted context:

- asset/analysis/model/document IDs selected during investigation;
- query text, status/type filters, and optional point ID;
- action justification drafted from evidence;
- requested changes/parameters.

Risks:

- Header spoofing is sufficient to assume another role.
- A user from one company can read or act on another company’s IDs if they know them.
- Permission alone is checked; ownership, case scope, and asset/model scope are not.
- Static OpenAPI global security falsely suggests all reads authenticate.
- `case_id`, `company_id`, and `asset_id` from `cases.json` are caller-visible context, not proof of authorization.

## 6. Probabilistic API Behaviour

`resolve_mode` supports five modes with the default distribution:

| Mode | Weight | Runtime transformation |
|---|---:|---|
| `complete` | 0.60 | full payload |
| `partial` | 0.15 | drops category-specific fields |
| `inconclusive` | 0.10 | usually retains only `asset_id` plus marker |
| `conflict` | 0.08 | adds `conflict=true`; payload otherwise retained |
| `unavailable` | 0.07 | usually returns empty data |

Partial field removal:

| Category | Removed fields |
|---|---|
| analyses | `evidence`, `limitations` |
| baseline | `features` |
| data quality | `freshness_minutes` |
| RMS | `samples` |
| model | `requirements`, `last_run_at` |
| spectrum | none in `_PARTIAL_DROP`; incompleteness relies on seeded `bands_missing` |

Seed precedence and reproducibility:

1. Fixed `overrides[resource][category]` always win.
2. `seed=complete` forces complete if there is no override.
3. `seed=degraded` forces partial if there is no override.
4. Other seeds hash `seed|resource|category` into the distribution.
5. Omitting seed hashes the constant `noseed|resource|category`.

Despite documentation saying no-seed behavior is “sampled,” it is deterministic and stable per resource/category, not a fresh random draw per request or process. The dead unreachable `return Mode(ov[category])` after `return Mode.PARTIAL` has no runtime effect.

Fixed scenario overrides include G501 analysis/RMS/quality/baseline degradation, C710 complete RMS, S420 and M205 analysis conflict, M208 partial analyses, M605 partial spectrum, and V301 partial data quality.

Other behavioral states identified in data are not envelope modes:

- `pending`, `delayed`, `failed` processing;
- `stale` analysis and `staleness_flag` quality;
- `learning`/`invalidated` baseline;
- low completeness/SNR;
- coverage partial or baseline not learnable.

Why this matters later:

- Adaptive investigation must choose complementary evidence when a critical field is absent.
- Stop policy must not treat HTTP 200 as sufficient evidence.
- Human handoff needs explicit thresholds for unavailable/inconclusive/conflicting evidence.
- Robustness evaluation needs both fixed repeatable seeds and varied seeds; current no-seed calls do not measure run-to-run randomness.
- Retries with the same seed/resource cannot improve the mode. A retry policy must know whether it is retrying transport availability or deterministic synthetic degradation.

## 7. Contract vs Runtime Findings

The two static contracts have identical SHA-256 hashes (`8B3FDC5DA50A8FA2923928A2F5AEBCFE5034C622DBA222DF84F56ABCD0B4AABF`). Twelve divergence groups were recorded:

| # | Static contract | Implementation / expected FastAPI OpenAPI | Tests / expected paths | Future-tool impact |
|---:|---|---|---|---|
| 1 | `/assets/{assetId}` appears twice as a YAML mapping key | runtime correctly registers GET and PATCH | both are used | a normal YAML parser may silently lose one operation; contract is unsafe for generation |
| 2 | global `security: UserContext` applies to every operation | only `/users/me` and ACTIONs require the header | reads omit headers | generated clients may unnecessarily require identity; runtime is more permissive than documented security |
| 3 | camelCase path names (`assetId`, etc.) | runtime generated spec uses snake_case (`asset_id`) | paths use concrete IDs | schemas/operation signatures will differ across sources |
| 4 | explicit camelCase `operationId` values | FastAPI defaults derive IDs from function/path/method | tests do not use IDs | generated tool/client names are unstable across static/runtime specs |
| 5 | GET response schemas point to `QueryEnvelope` or descriptions | handlers have no response models, so generated runtime schemas are generic/empty | tests assert concrete shapes | tools need manually validated output schemas, not runtime generation alone |
| 6 | `Asset` is nested (`hierarchy`, `config`) | runtime returns flat parquet columns plus `points` | tests access flat `machine_type` | contract-generated deserialization and agent field expectations will fail |
| 7 | data-quality documents only `seed` | runtime also accepts `point_id` | scenarios currently omit it | useful selector is missing from static tool schema |
| 8 | `status` and knowledge `type` have enums | runtime accepts any string and returns an empty filtered list for invalid values | negative enum behavior untested | tools must validate enum values themselves if desired |
| 9 | `ActionRequest` and PATCH `changes` describe structured input | runtime body is arbitrary `dict`; only justification is checked | success tests pass valid-looking input but do not test invalid action params | action tools cannot assume API-side semantic validation |
| 10 | actions say updated/request accepted | none writes to parquet/cache/queue; all only generate a UUID response | CEN-15 expects a validation GET; tests check only acceptance | tools must not claim durable state change; postcondition cannot currently be verified |
| 11 | documented responses omit several 401/403/404/422 outcomes | runtime dependencies and FastAPI validation can emit them; error schemas differ for 422 | only a subset is tested; specialist route has no API test | retry/error policies generated from contract will be incomplete |
| 12 | docs describe no-seed as sampled and assets as stable | no-seed uses deterministic hash; single asset category is `asset`, not stable `assets` | seed determinism tested only for explicit seed | evaluation design may mismeasure variability and reads may unexpectedly lose single-asset context |

Additional schema observations:

- Runtime `/users/me` is unwrapped while nearly all other reads are enveloped.
- Static `Spectrum` includes `frequency_resolution_hz`, but parquet/runtime rows do not guarantee that field.
- Static comments mention envelope `{status, data, mode, notes?}`, but implementation has no `status` field.
- Contract action errors are inconsistently enumerated by route.
- FastAPI’s 422 response shape does not follow `{code, message}` because only `HTTPException` is custom-handled.

Runtime limitation: the application could not be launched and `/openapi.json` could not be captured in this environment. These comparisons should be re-run against the generated document when Python is available.

## 8. Support Case → API Mapping

The catalog contains 17 tickets represented by 17 agent input cases. The evaluation condenses them into 16 scenarios because CEN-07 combines INV-09 with EXE-12.

| Ticket / asset | Customer problem and investigation objective | Relevant/expected reads | Possible action | Expected outcome |
|---|---|---|---|---|
| CTX-01 / M101 | bearing replacement procedure | asset, knowledge search/doc, baseline | none | applicable procedure; warn baseline invalidation after maintenance |
| CTX-02 / B204 | define BPFO and connect it to evidence | knowledge search/doc, spectrum, analyses | none | definition grounded in asset peak/evidence |
| CTX-03 / V301 | explain RMS alarm threshold | knowledge search, baseline, RMS, quality | none | threshold 4.6 derived from reference+tolerance, not fixed table |
| INV-04 / G501 | failure without prior alert | asset, analyses, baseline, quality, RMS, model | escalate if remote evidence exhausted | learning baseline + absent data explain inability to alert |
| INV-05 / C710 | rising RMS without insight | RMS, baseline, pending analyses, model, quality | reprocess or specialist only if justified | threshold exceeded; analysis pending; model delayed |
| INV-06 / S420 | suspected false positive | analysis 9903/9904, baseline, spectrum, model | retraining only on stronger systematic evidence | old invalidated baseline and specialist conflict undermine imbalance |
| INV-07 / M605 | electrical vs mechanical abrupt vibration | asset electrical config, RMS, spectrum, knowledge | request more data / specialist | missing 2× line band makes conclusion uncertain |
| INV-08 / M205 | automatic vs specialist disagreement | analyses 9907/9908, spectrum, knowledge | possibly specialist/human review | subharmonics support looseness over misalignment |
| INV-09 / B204 | stale insight after bearing change | analysis 9906, baseline, quality/RMS | reprocess | stale analysis + invalidated baseline confirmed |
| INV-10 / V301 | trust high-confidence insight with poor signal | analysis 9909, quality, model requirements, baseline/spectrum | avoid high-impact action | measured quality below model requirement weakens confidence |
| INV-11 / M102 | model support for old DC motor | asset, model, baseline | avoid unsupported retraining assumption | supported class but cannot learn baseline |
| INV-11b / M208 | lubrication found without baseline | analysis 9905, baseline, knowledge, optionally spectrum | none | symptom mode is valid without learned baseline |
| EXE-12 / B204 | reprocess after intervention | analysis 9906, baseline, post-intervention RMS | reprocess | accepted with evidence-based justification |
| EXE-13 / C710 | specialist review requested | asset analyses, analysis 9902, baseline | request specialist | accepted for `action_low` user with justification |
| EXE-14 / V301 | lower criticality | current asset | PATCH config | API says accepted; current runtime cannot verify persistence |
| EXE-15 / S420 | retrain due to repeated wrong insight | conflicting analyses, model | request retraining | accepted for `action_high`; evidence must support systematic error |
| EXE-16 / G501 | field/human support needed | INV-04 evidence or case context | escalate | accepted for user with `escalate` |

Documentation inconsistency to resolve: the support ticket calls the EXE-13 user a “Coordenador,” while the actual case uses `usr_sofia`, a reliability analyst with `action_low`. The scenario audit explicitly records that correction because the route requires `action_low`, not `escalate`.

## 9. Expected Paths Analysis

`eval/expected-paths.json` contains 17 case paths. These paths align with the 16 scenario narratives and are valuable as post-run evaluation references, but they are neither the only valid investigation nor an execution policy.

Observed characteristics:

- Paths prioritize evidence chains, e.g. analysis → baseline → spectrum, rather than single-call answers.
- Four cases culminate in the matching ACTION route; INV-04 also proposes escalation.
- Some useful support-ticket APIs do not appear in the minimal expected path, such as model coverage in INV-04 or knowledge in INV-07/08.
- Expected paths embed concrete internal IDs (`an_9903`, `mdl_vib_v3`, knowledge IDs). A real agent should discover or receive these through legitimate context rather than memorize them.
- CEN-15 expects GET → PATCH → GET verification, which exposes the non-persistence mismatch.
- Evaluation must allow semantically equivalent paths, extra justified evidence calls, and early stopping when modes make a claim unsafe.

Data-leakage boundary:

- Agent-visible: `agent-input/cases.json`, its static API contract, trusted application context, and live API results.
- Evaluator-only: `eval/expected-paths.json`, `docs/test-scenarios.md`, `data/cases.parquet`, root questions, expected modes, and expected conclusions.
- Traces may be compared with expected paths only after the agent run completes.

## 10. Candidate Tool Inventory

This is a proposal only; no tool has been implemented.

| Suggested name | Endpoint | Minimum arguments | Necessary return | Kind | Risks/notes |
|---|---|---|---|---|---|
| `get_company_context` | GET company | company ID, optional seed | envelope + identity fields | READ | tenant ID must be trusted/authorized |
| `list_company_assets` | GET company assets | company ID, optional seed | asset summaries + mode | READ | potentially broad enumeration |
| `get_current_user_context` | GET users/me | trusted identity injection | role, company, permissions | READ | agent must not choose header |
| `get_asset_context` | GET asset | asset ID, optional seed | flat actual payload + points | READ | normalize contract/runtime shape |
| `list_asset_analyses` | GET analyses | asset ID; optional status/seed | analysis list + mode | READ | validate status enum |
| `get_analysis_evidence` | GET analysis | analysis ID, optional seed | evidence/confidence/limitations + mode | READ | partial may remove decisive fields |
| `get_asset_baseline` | GET baseline | asset ID; optional point/seed | lifecycle, features, learnable + mode | READ | null baseline is 200/inconclusive |
| `get_asset_rms_series` | GET RMS | asset ID; optional point/seed | threshold and samples + mode | READ | partial removes samples |
| `get_asset_spectrum` | GET spectrum | asset ID; optional point/seed | peaks, missing bands + mode | READ | missing critical band blocks diagnosis |
| `get_asset_data_quality` | GET quality | asset ID; optional point/seed | completeness/SNR/freshness + mode | READ | point selector absent in static contract |
| `get_model_capabilities` | GET model | model ID, optional seed | coverage, requirements, processing | READ | partial removes requirements |
| `search_industrial_knowledge` | GET search | q; optional type/seed | result metadata/body + mode | READ | broad/full document output; validate type |
| `get_knowledge_document` | GET doc | doc ID, optional seed | document + mode | READ | ground applicability in asset context |
| `request_asset_config_update` | PATCH asset | trusted user, asset, validated changes, justification | acceptance plus requested postcondition | ACTION | high impact; API does not persist/validate changes |
| `request_analysis_reprocess` | POST reprocess | trusted user, analysis, justification | acceptance ID/message | ACTION | duplicate requests; no status/idempotency |
| `request_specialist_analysis` | POST specialist | trusted user, analysis, justification | acceptance ID/message | ACTION | cost/queue effect implied but not observable |
| `request_model_retraining` | POST retraining | trusted user, model, justification/evidence | acceptance ID/message | ACTION | high impact; needs human policy gate |
| `escalate_support_case` | POST escalate | trusted user/case, evidence-grounded justification | acceptance ID/message | ACTION | case/company association not enforced |

ACTION candidates should never expose `x-user-id` as a free model argument. Their future interface needs explicit confirmation/policy handling, idempotency, validated domain fields, and truthful acknowledgement semantics. This is a requirement finding, not an implementation decision for this step.

## 11. Risks for Agent Architecture

1. **Identity and tenant bypass:** spoofable user header and absent ownership checks allow cross-company reads/actions.
2. **False action completion:** acceptance responses imply effects that are never persisted; user-facing claims could be materially wrong.
3. **Broken code generation:** duplicate YAML key can erase an operation, while static and runtime names/schemas diverge.
4. **HTTP-success ambiguity:** unavailable/conflict/inconclusive evidence uses 200, so naïve tools may treat failure as fact.
5. **Evaluation leakage:** concrete expected paths and root answers are stored near agent inputs and also inside `cases.parquet`.
6. **No idempotency:** repeated action calls create new action IDs with no deduplication or durable record.
7. **Insufficient input validation:** action fields, status, and knowledge type are not semantically validated.
8. **No auditable postcondition:** actions have no persisted status or read-after-write evidence.
9. **Determinism mismatch:** no-seed behavior is stable, not stochastic per execution; robustness experiments could be misdesigned.
10. **Response-shape drift:** static models, runtime dictionaries, and degraded payloads require defensive parsing.
11. **Trace requirements:** record trusted user/company/case, endpoint, normalized args, seed, HTTP status, mode/notes, evidence fields used, permission decision, action justification, confirmation, action ID, and postcondition.
12. **Evidence Ledger opportunity:** claims should link to source call, resource/time, mode, field path, and conflict/quality limitations; otherwise explanations cannot be audited.

Endpoints that should not be directly controlled by an LLM without an application gate are all five ACTION operations, particularly configuration update and retraining. Human handoff is safer than an industrial change but still creates workload and needs over-escalation control.

## 12. Open Questions

Questions requiring human/product decision before Step 02:

1. Is `x-user-id` intentionally a local-demo identity only, and what authenticated principal/tenant mechanism should future tools trust?
2. Should READ endpoints be anonymous as runtime implements, or authenticated as the static contract declares?
3. Are ACTION routes intentionally simulated acknowledgements, or must they persist state/events before an agent can truthfully use them?
4. What exact schemas and allowed fields apply to asset config, reprocess parameters, specialist requests, retraining evidence, and escalation context?
5. Which actions require explicit user confirmation or mandatory human approval beyond permission and a 20-character justification?
6. What are the idempotency and retry semantics for each action?
7. Should fixed scenario overrides defeat `seed=complete`, or should exploration mode be able to bypass them?
8. Is no-seed behavior intended to vary per request? If yes, current hashing does not implement that intent.
9. Which artifact is authoritative for tool generation: corrected static OpenAPI or captured runtime OpenAPI plus overlays?
10. Should evaluation accept alternative valid trajectories, and how will extra calls, early handoff, and unavailable evidence be scored?

## 13. Test Execution Results

Attempted command from `api/`:

```powershell
python --version
python -m pytest -q
```

Result:

| Item | Result |
|---|---|
| Tests discovered statically | 39 (`def test_...`) |
| Executed | 0 |
| Passed | not measured |
| Failed | not measured |
| Environment error | `python` command not found |
| Alternative launchers checked | `py`, `python3`, `uv` unavailable |
| API started | no |
| `/openapi.json` captured | no |

The repository documentation claims all 39 assertions were green when published. That is historical documentation, not a result of this audit run.

Static test coverage strengths:

- representative reads, 404s, modes, explicit seed determinism, and overrides;
- action authentication/permission for several routes;
- justification validation for reprocess;
- domain cases for baseline, symptom detection, threshold, model coverage, and knowledge.

Static test gaps:

- no direct tests for `request-specialist`;
- no action-specific body validation or state persistence assertions;
- no tenant/ownership isolation;
- no static-contract parsing or contract/runtime diff test;
- incomplete negative tests per action (400/401/403/404/422 matrix);
- no verification of custom vs FastAPI 422 error envelopes;
- no test proving no-seed run-to-run sampling, because it does not occur.

## 14. Recommended Inputs for Step 02

Step 02 should not begin until this audit is reviewed and the open questions are decided. When authorized, its inputs should be:

- a corrected, single-source OpenAPI contract with unique path keys;
- captured and versioned `/openapi.json`, with an automated diff against the static contract;
- an approved identity/tenant context contract and permission matrix;
- approved domain schemas and postconditions for all five actions;
- confirmation, idempotency, retry, and timeout policies;
- normalized response/envelope and error taxonomy, including 422;
- a mode-aware evidence policy and stop/handoff criteria;
- an evaluator-only expected-path package isolated from agent runtime;
- a trace schema and Evidence Ledger fields;
- a repeatable test environment with Python dependencies and a recorded green baseline.

No LangGraph, agent, prompt, tool, wrapper, queue, Redis, worker, judge, evaluation framework, RAG, interface, or architectural refactor was created in this step.
