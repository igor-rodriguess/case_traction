# Runtime Validation

Validation date: 2026-08-29
Scope: runtime discovery, dependency workflow, Git baseline, execution readiness, static/runtime-contract preparation, and evaluation-data isolation.
Constraint: no API behavior, endpoint, permission, static OpenAPI, or existing test was changed.

## 1. Executive Summary

The repository expects Python **3.10 or newer** and uses **uv** as its documented environment/dependency manager. The API package is declared in `api/pyproject.toml`, with development dependencies in the `dev` extra. There is no `uv.lock`, requirements file, Poetry lock, Dockerfile, or Compose file, so dependency installation is constrained by lower bounds but is not bit-for-bit locked.

No usable Python or uv command is available in the current PATH. `Get-Command` could not resolve `py`, `python`, `python3`, or `uv`; `where.exe` found none. Direct version checks were attempted but the combined check timed out instead of yielding a usable executable. A previous isolated `python --version` attempt returned “command not found.” Under the stage instructions, execution therefore stopped before environment creation or installation.

Consequences:

- no `.venv` was created;
- no dependency was installed;
- the 39 statically discovered tests were not collected or run;
- FastAPI was not started;
- Swagger and `/openapi.json` were not queried;
- `docs/architecture/runtime-openapi.json` was deliberately not created, because a hand-authored approximation would violate the requirement that it exactly capture the live endpoint.

Static evidence still confirms 18 FastAPI route decorators and 18 method entries in the static YAML. It also confirms the suspected duplicate YAML key: `/assets/{assetId}` occurs twice, once for GET and once for PATCH. Twelve previously identified contract/implementation finding groups remain open; a definitive three-way static/implementation/runtime count awaits a runtime capture.

Final readiness classification: **BLOCKED**, specifically on the absence of a Python/uv runtime needed to prove tests, startup, HTTP behavior, and generated OpenAPI.

### Continuation run — environment unblocked

The environment was prepared after the first run. This continuation preserves the original BLOCKED evidence above and completes the previously impossible checks.

| Measure | Continuation result |
|---|---|
| Selected Python | CPython 3.12.10 (`python`) |
| Other Python launchers | `py` and `python3` report 3.14.3 |
| uv | not globally available; uv 0.12.7 bootstrapped only inside `api/.venv` |
| Local environment | `api/.venv`, created successfully |
| Dependency install | 34 packages installed from `api/pyproject.toml` `.[dev]` |
| Original tests | 39 collected; 39 passed; 0 failed; 0 skipped; 1 warning; 42.38 s |
| API | started successfully on `127.0.0.1:8000` and stopped cleanly |
| Swagger | HTTP 200; Swagger UI present |
| Runtime OpenAPI | HTTP 200; captured directly to `runtime-openapi.json` |
| Runtime inventory | OpenAPI 3.1.0; 17 paths; 18 operations |
| Semantic modes | complete, partial, inconclusive, conflict, unavailable all confirmed over HTTP 200 |
| Final status | **READY_WITH_WARNINGS** |

## 2. Environment Detection

### Operating system and shell

- OS family: Windows
- Shell: PowerShell
- Project root used: `C:\Users\Inteli\Documents\Traction\case_traction\inteli-tractian-project`

### Required runtime

Evidence from repository files:

- `README.md` and `QUICKSTART.md`: Python ≥3.10 and uv.
- `api/pyproject.toml`: `requires-python = ">=3.10"`.
- `Makefile`: defaults to `PYTHON ?= python3`, creates `api/.venv` with uv, and runs tests/API through that venv.

### Commands checked

| Check | Result |
|---|---|
| `py --version` | no usable command resolved; direct combined probe timed out |
| `python --version` | command not found in the earlier isolated attempt; not resolved by `Get-Command` |
| `python3 --version` | no usable command resolved; direct combined probe timed out |
| `uv --version` | no usable command resolved; direct combined probe timed out |
| `where.exe py` | no files found |
| `where.exe python` | no files found |
| `where.exe python3` | no files found |
| `where.exe uv` | no files found |
| `Get-Command py,python,python3,uv` | all `NOT_FOUND` |

The sandbox denied inspection of a common user-level installation directory outside the workspace. That does not change the operational result: no launcher is available through the shell used by the project.

### Continuation detection result

The new shell PATH contained the installed runtime directories, but sandbox restrictions initially hid those external executables. Read-only detection outside the sandbox produced:

```text
py --version      → Python 3.14.3
python --version  → Python 3.12.10
python3 --version → Python 3.14.3
uv --version      → command not found
```

`where.exe` resolved `py.exe`, the Python 3.12 executable, and Windows aliases. It did not resolve uv. Both `py -m uv` and `python -m uv` confirmed that uv was not installed as a module. Python 3.12.10 was selected because it satisfies `>=3.10`, matched the previously documented conservative target, and avoids making the newer 3.14 runtime an untested compatibility assumption.

### Minimal human preparation

No installation was performed. A human can unblock the environment with an approved Python ≥3.10 installation and uv installation. A conservative Windows target is Python 3.12, which satisfies the project declaration. After installation, open a new shell and prove discovery:

```powershell
py --version
python --version
uv --version
where.exe py
where.exe python
where.exe uv
```

Only one Python launcher needs to work. If `py` works and `python` does not, use `py` for bootstrap checks; uv can select the installed interpreter directly.

## 3. Dependency Management

### Repository-defined workflow

The intended workflow is:

```text
make setup
  ├─ uv venv --python <python>          → api/.venv
  ├─ uv pip install -e ".[dev]"        → API + test dependencies
  └─ regenerate data and packaged inputs
```

Declared runtime dependencies:

- FastAPI ≥0.110
- Uvicorn standard ≥0.29
- Pydantic ≥2.6
- PyArrow ≥15
- pandas ≥2.0
- PyYAML ≥6

Development dependencies:

- pytest ≥8
- httpx ≥0.27

### Reproducibility assessment

- Manager: uv is explicitly documented and used by the Makefile.
- Package source: `api/pyproject.toml`, editable install with `.[dev]`.
- Lock file: absent.
- Version strategy: minimum bounds only.
- Reproducibility level: workflow-reproducible, but not dependency-version reproducible. Two installs at different dates can resolve different versions.
- The Makefile assumes POSIX venv paths (`.venv/bin/python`) and tools such as `command`, `nohup`, and `pkill`; it is not directly portable to native PowerShell.

### Minimal Windows commands after runtime approval

These preserve the repository’s uv/pyproject approach without running `make setup` and therefore without regenerating data, agent input, or evaluator artifacts:

```powershell
Set-Location api
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q
```

If a different approved Python ≥3.10 is installed, replace `3.12` with that interpreter/version. A future lock-file decision is separate from this validation step and was not made here.

### Actual result in this run

| Item | Result |
|---|---|
| Runtime | unavailable |
| Python version | not measurable |
| Manager invoked | none |
| Environment created | no |
| Dependencies installed | no |
| Installation errors | not applicable; installation did not begin |

### Continuation installation result

Because uv was still absent globally, the smallest local-only bootstrap was used:

```powershell
Set-Location api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install uv
.\.venv\Scripts\uv.exe pip install --python .\.venv\Scripts\python.exe -e ".[dev]"
```

Results:

- Python: 3.12.10;
- pip used only to bootstrap the project-selected manager inside the venv: 25.0.1;
- local uv: 0.12.7;
- uv resolved and installed 34 packages successfully;
- FastAPI 0.141.1, Uvicorn 0.52.4, Pydantic 2.13.5, pandas 3.0.5, PyArrow 25.0.1, pytest 9.1.1, and httpx 0.28.1 were among the resolved versions;
- no global dependency was installed;
- the absence of a lock file remains, so this successful resolution is not guaranteed to reproduce the same versions later.

## 4. Git Baseline

Baseline was captured before this stage wrote any file.

| Field | Value |
|---|---|
| Branch | `main` |
| Commit | `6b06f6ebc44d0a8ce351948b0d086f441ca23283` |
| Status | `?? __MACOSX/`, `?? inteli-tractian-project/` |

The entire project directory is untracked from the parent repository’s perspective. Git therefore cannot distinguish original project files, the Step 01 audit files, and later per-file modifications. At the start of this stage, the Step 01 artifacts already existed:

- `docs/architecture/01-api-domain-audit.md`
- `docs/architecture/01-endpoint-inventory.json`

No pre-existing file was reverted, staged, or committed. This stage adds only this report. Because the project is wholly untracked, `git diff` cannot provide a useful file-level before/after diff until the user chooses a tracking baseline.

The continuation began on the same branch and commit with the same whole-project-untracked limitation. It created local environment/cache directories and the two requested validation artifacts; it did not modify source, tests, static contracts, or data.

## 5. Test Execution

### Project-defined command

The Makefile runs:

```text
api/.venv/bin/python -m pytest -q
```

The native Windows equivalent after environment creation is:

```powershell
api\.venv\Scripts\python.exe -m pytest -q
```

### Result

| Measure | Result |
|---|---|
| Test functions discovered statically | 39 |
| Tests collected by pytest | 0 (pytest could not run) |
| Passed | not measured |
| Failed | not measured |
| Skipped | not measured |
| Duration | not measured |
| Warnings | not measured |
| Classification | environment blocker |

### Continuation test result

Command executed without modifying the suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -ra
```

```text
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0
collected 39 items
tests\test_api.py ....................................... [100%]
39 passed, 1 warning in 42.38s
```

| Measure | Measured result |
|---|---:|
| Collected | 39 |
| Passed | 39 |
| Failed | 0 |
| Skipped | 0 |
| Warnings | 1 |
| Duration | 42.38 s |

The warning was `StarletteDeprecationWarning`: using `httpx` with `starlette.testclient` is deprecated and Starlette recommends `httpx2`. It is dependency/API evolution rather than an application test failure. No dependency pin or code change was made in response.

No test or production file was modified. The statement in `docs/test-scenarios.md` that 39 assertions were green is repository documentation from an earlier environment, not evidence from this run.

After environment preparation, capture the complete pytest terminal output and preferably run a second non-quiet collection command if exact node IDs are needed:

```powershell
api\.venv\Scripts\python.exe -m pytest -q
api\.venv\Scripts\python.exe -m pytest --collect-only -q
```

## 6. API Startup Validation

### Documented startup

The Makefile runs Uvicorn on `127.0.0.1:8000` with `app.main:app` from `api/`. The native Windows foreground command is:

```powershell
Set-Location api
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Expected standard FastAPI resources based on application construction:

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI: `http://127.0.0.1:8000/openapi.json`
- Health endpoint: none is defined in `api/app/main.py`

### Actual result

| Check | Result |
|---|---|
| Application initialized | no; runtime unavailable |
| Port bound | no |
| Health endpoint | none statically defined |
| Swagger accessed | no |
| `/openapi.json` accessed | no |
| Orphan process | none; no process was started |

### Continuation startup result

The documented application target was started with the Windows venv equivalent:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Validation results:

| Check | Measured result |
|---|---|
| Application startup | successful; Uvicorn logged “Application startup complete” |
| Host/port | `127.0.0.1:8000` |
| Basic company endpoint | HTTP 200 |
| Health endpoint | none defined |
| Swagger `/docs` | HTTP 200; Swagger UI marker present |
| `/openapi.json` | HTTP 200 |
| Cleanup | exact launched process stopped; port 8000 verified free |

No API process was left running.

When the environment is available, use a foreground process or a tracked PowerShell process object, query the endpoints, and terminate that exact process in `finally`; do not rely on broad process killing.

## 7. Runtime OpenAPI

`docs/architecture/runtime-openapi.json` was **not created**.

Reason: the requested artifact must be the exact response from `/openapi.json`. FastAPI could not start without Python, and manually synthesizing the document from source would not be an exact runtime capture.

Static implementation inventory:

- 18 `@app.get/post/patch` decorators;
- 17 unique path templates;
- 13 GET operations;
- 4 POST operations;
- 1 PATCH operation;
- 13 READ and 5 ACTION by semantics.

Required capture command after startup:

```powershell
Invoke-WebRequest -Uri 'http://127.0.0.1:8000/openapi.json' -OutFile '..\docs\architecture\runtime-openapi.json'
```

The capture must be performed while running the unmodified current application and should be validated as JSON immediately afterward.

### Continuation capture result

The file was captured directly with `Invoke-WebRequest -OutFile` from the live unmodified API. It was not constructed or reformatted manually.

| Property | Value |
|---|---|
| File | `docs/architecture/runtime-openapi.json` |
| Size | 14,684 bytes |
| SHA-256 | `DBB5F363E25740DE0E3061C5CB593DD23E19614EFB72F6358C480EB8864C6635` |
| OpenAPI version | 3.1.0 |
| Paths | 17 |
| Operations | 18 |
| Methods | 13 GET, 4 POST, 1 PATCH |

## 8. Static vs Runtime Contract

### Status of the three sources

| Source | Available? | Evidence level in this run |
|---|---|---|
| FastAPI implementation | yes | statically inspected |
| Static OpenAPI (docs and agent-input) | yes | statically inspected; files are byte-identical per Step 01 |
| Generated runtime OpenAPI | no | blocked by missing runtime |

### Per-operation comparison

“Runtime expected” below is inferred from FastAPI decorators and signatures, not captured `/openapi.json`.

| Operation | Implementation | Static YAML | Runtime expected / open issue | Kind |
|---|---|---|---|---|
| GET company | exists; `{company_id}`, `seed` | exists; `{companyId}`, `seed` | snake_case path parameter; generic response schema | READ |
| GET company assets | exists; `{company_id}`, `seed` | exists; `{companyId}`, `seed` | generic response schema | READ |
| GET users/me | exists; header dependency | exists; explicit security | runtime header parameter/security representation must be captured | READ |
| GET asset | exists; `{asset_id}`, `seed` | first duplicated asset key | FastAPI should retain GET; static YAML parser may lose it | READ |
| PATCH asset | exists; arbitrary dict body, `action_high` | second duplicated asset key; structured changes | FastAPI should retain PATCH; runtime body will be generic object | ACTION |
| GET asset analyses | exists; `status`, `seed` | exists; status enum | implementation does not enforce enum | READ |
| GET analysis | exists; `{analysis_id}`, `seed` | exists; `{analysisId}` | generic response schema | READ |
| POST reprocess | exists; arbitrary dict, `action_low` | exists; `ActionRequest` | runtime body/status schemas differ | ACTION |
| POST specialist | exists; arbitrary dict, `action_low` | exists; `ActionRequest` | no direct existing API test; runtime capture pending | ACTION |
| GET baseline | exists; `point_id`, `seed` | exists | generic response; 200/inconclusive null possible | READ |
| GET RMS | exists; `point_id`, `seed` | exists | generic response schema | READ |
| GET spectrum | exists; `point_id`, `seed` | exists | static schema may promise fields not guaranteed by data | READ |
| GET data quality | exists; `point_id`, `seed` | exists but omits `point_id` | runtime should expose extra query parameter | READ |
| GET model | exists; `{model_id}`, `seed` | exists; `{modelId}` | implementation normalizes `requirements`; generic response schema | READ |
| POST retraining | exists; arbitrary dict, `action_high` | exists; `ActionRequest` | runtime body/status schemas differ | ACTION |
| GET knowledge search | exists; required `q`, optional `type`, `seed` | exists; type enum | implementation does not enforce enum; 422 possible | READ |
| GET knowledge document | exists; `{doc_id}`, `seed` | exists; `{docId}` | generic response schema | READ |
| POST case escalation | exists; arbitrary dict, `escalate` | exists; `ActionRequest` | runtime body/status schemas differ | ACTION |

### Duplicate YAML key confirmation

Confirmed statically:

- `docs/api-contract.openapi.yaml` contains **18 method entries**.
- It contains `/assets/{assetId}:` **twice** at the same mapping level.
- The first occurrence contains GET.
- The second occurrence contains PATCH.
- `api/app/main.py` independently registers both GET and PATCH on `/assets/{asset_id}`.

This is a real structural defect in the static YAML. A conforming mapping should contain one path key with both methods. Many YAML loaders keep only the last duplicate, so GET can silently disappear. The static OpenAPI was not corrected in this stage.

### Remaining divergences

The 12 Step 01 finding groups remain open:

1. duplicate YAML path key;
2. global static security vs selective runtime header use;
3. camelCase vs snake_case parameter names;
4. explicit static vs generated operation IDs;
5. typed static vs generic runtime response schemas;
6. nested static vs flat actual Asset payload;
7. missing static `point_id` on data quality;
8. static enums not enforced by implementation;
9. structured action schemas vs arbitrary runtime dicts;
10. declared actions vs no persisted effect;
11. incomplete documented error/status schemas, including 422;
12. documentation/implementation mismatch in no-seed and stable-asset behavior.

The exact divergence count against the generated runtime document remains unverified until capture.

### Final three-way comparison

The runtime capture resolves the principal uncertainty:

- runtime has both `GET /assets/{asset_id}` and `PATCH /assets/{asset_id}` under one path object;
- implementation has matching GET and PATCH decorators;
- textual static YAML contains 18 method entries but repeats `/assets/{assetId}:` twice;
- PyYAML parses the static document into only 17 operations and retains PATCH while silently losing GET;
- runtime contains 18 operations, so the missing parsed static operation is exactly `GET /assets/{asset_id}` after path-parameter normalization.

The **12 material divergence groups remain** and are now runtime-confirmed rather than inferred. Every runtime operation is affected by at least one group. This count deliberately groups a systematic discrepancy once (for example, operation-ID generation or error-schema drift) rather than inflating the count for every endpoint occurrence.

Additional concrete runtime evidence:

- runtime uses snake_case paths/parameter names and generated operation IDs;
- runtime publishes no `securitySchemes` and no global `security`; `x-user-id` appears as an optional header parameter on dependent routes;
- all parameterized/body operations publish 422 in addition to 200, while static status documentation is inconsistent;
- all five action bodies are generic `object` with `additionalProperties: true`, unlike the static `ActionRequest` schemas;
- untyped handler responses produce generic runtime 200 schemas, so runtime OpenAPI alone does not capture actual envelope payloads;
- data-quality runtime includes `point_id`, missing from the static contract;
- the 39 tests pass but do not eliminate semantic gaps such as action non-persistence or tenant isolation.

## 9. HTTP vs Semantic Status Findings

Live HTTP confirmation was blocked. Static code and existing tests nevertheless prove the control flow: GET handlers return an envelope directly for all modes and do not raise an HTTP error for semantic degradation. FastAPI therefore uses the normal 200 response unless a resource lookup raises 404 or input validation raises 422.

| Evidence status | Concrete resource/call | Static evidence | Expected transport status |
|---|---|---|---:|
| complete | `GET /assets/asset_M101?seed=complete` | test asserts `mode=complete` | 200 |
| partial | M208 analyses, M605 spectrum, V301 quality overrides | `seed.json`/seed data overrides and mode transform | 200 |
| inconclusive | `GET /assets/asset_G501/analyses` | override plus existing test asserts mode | 200 |
| conflict | S420 or M205 analyses | fixed override; payload adds `conflict=true` | 200 |
| unavailable | `GET /assets/asset_G501/rms` | existing test asserts `mode=unavailable`, `data={}` | 200 |

The essential distinction is:

```text
transport_status = HTTP protocol outcome (for example 200)
evidence_status  = envelope.mode (for example unavailable)
```

This distinction is confirmed by static implementation/test evidence, but not by a live request in this stage. Future runtime validation must record both fields for the five examples above. No normalization was implemented.

### Live continuation evidence

| Requested example | Live request | HTTP transport status | Semantic/evidence status |
|---|---|---:|---|
| complete | `GET /assets/asset_M101?seed=complete` | 200 | `complete` |
| partial | `GET /assets/asset_M605/spectrum` | 200 | `partial` |
| inconclusive | `GET /assets/asset_G501/analyses` | 200 | `inconclusive` |
| conflict | `GET /analyses/an_9903` | 200 | `conflict` |
| unavailable | `GET /assets/asset_G501/rms` | 200 | `unavailable` |

The behavior is now confirmed by live HTTP, not merely source inspection. In particular, `unavailable`, `inconclusive`, and `conflict` are evidence states carried inside successful HTTP 200 responses. No normalization was added.

## 10. Source-of-Truth Recommendation

Provisional hierarchy for the future TractianClient:

1. **Observed HTTP behavior under automated tests** — authoritative for actual request/response semantics, once this environment can run it.
2. **Version-matched generated `/openapi.json`** — authoritative for the routes, parameters, bodies, status schemas, and security metadata that FastAPI publishes, but insufficient alone because current handlers lack precise response models.
3. **FastAPI implementation and store/probability code** — authoritative for behavior not expressed by the generated schema: envelopes, modes, permission checks, justification rules, and non-persistence.
4. **Static OpenAPI** — an intent/specification source to identify desired names and schemas, not safe as a generator input while it has duplicate keys and known drift.
5. **Existing tests** — executable regression evidence and case examples; they complement observed behavior but do not cover every route/negative case.
6. **Narrative documentation and evaluation paths** — domain intent and evaluator guidance, never a wire-contract authority.

The practical recommendation is not to choose the static YAML alone. The client should eventually be based on a captured, versioned runtime OpenAPI and verified HTTP behavior, with explicit overlays/normalization derived from implementation where FastAPI emits generic schemas. This recommendation remains provisional until tests and runtime capture are completed.

### Final recommendation after runtime validation

The evidence hierarchy is now confirmed:

1. observed HTTP behavior protected by the green regression suite;
2. the version-matched captured runtime OpenAPI for actual operations and transport parameters;
3. implementation for envelope, permissions, modes, error details, and action semantics omitted from the runtime schema;
4. tests as regression evidence and usage examples;
5. static OpenAPI as intended contract only, pending correction in a separately authorized stage;
6. narrative documentation and expected paths as domain/evaluation material, never client wire truth.

The future TractianClient should not be generated directly from the current static YAML. Runtime OpenAPI is the best machine-readable base, but it requires explicit, reviewed overlays because its response and action-body schemas are generic.

## 11. Evaluation Data Isolation

Current locations:

| Artifact | Role | Future access policy |
|---|---|---|
| `agent-input/cases.json` | user message + minimal case context | agent/runtime input allowed |
| `agent-input/api-contract.openapi.yaml` | agent-facing static contract | allowed only after contract policy is decided |
| `eval/expected-paths.json` | expected trajectories/root answers | evaluator only, after execution |
| `eval/test-scenarios.md` | evaluation scenarios | evaluator only |
| `docs/test-scenarios.md` | commented scenarios and expected paths | evaluator/developer only; exclude from agent context |
| `data/cases.parquet` | includes root question, mode, expected path | evaluator/internal data; exclude from agent context |

Recommendation for subsequent stages:

- build the agent’s runtime package from an explicit allowlist rooted in `agent-input/`;
- deny `eval/`, `docs/test-scenarios.md`, and `data/cases.parquet` to prompt/retrieval/tool context;
- apply expected paths only to completed traces in the evaluation pipeline;
- never embed concrete expected IDs or conclusions into agent prompts;
- test the packaging boundary so evaluator files cannot be discovered through generic filesystem access.

No file was moved in this stage.

## 12. Remaining Risks

1. No live evidence yet proves dependency compatibility with the versions currently resolved by uv.
2. Lack of a lock file prevents exact dependency reproduction.
3. The POSIX Makefile path/process assumptions do not directly work in native Windows PowerShell.
4. Generated runtime OpenAPI remains unknown and may add divergence groups beyond the 12 known ones.
5. The static YAML duplicate path can corrupt code generation.
6. Semantic degradation over HTTP 200 is not yet demonstrated by a live request in this environment.
7. Actions acknowledge but do not persist state, so client postcondition semantics remain unresolved.
8. Header identity and tenant authorization remain unsafe for a real client.
9. The repository is wholly untracked, weakening change attribution and reproducible baselines.
10. Evaluation ground truth is colocated with the project and needs an enforceable runtime exclusion boundary.

Runtime availability, test execution, API startup, live semantic-mode checks, and OpenAPI capture are no longer risks. Remaining warnings are contract drift, unlocked dependencies, the TestClient deprecation warning, weak identity/tenant enforcement, action non-persistence, generic runtime schemas, and evaluation-data colocation.

## 13. Blockers for Step 02

Execution blockers:

- install or expose an approved Python ≥3.10 runtime;
- install or expose uv;
- create `api/.venv` and resolve `.[dev]` without modifying production code;
- run all tests and classify any failures;
- start the API and capture exact `/openapi.json`;
- execute the five mode examples and record HTTP status plus envelope mode;
- perform the final three-way contract diff.

Design warnings that remain after runtime preparation:

- decide the trusted identity/tenant boundary;
- decide whether actions are intentionally simulated or require persistence;
- decide the authoritative/normalized schema for a future client;
- define action validation, confirmation, idempotency, and postconditions.

The missing runtime is a genuine blocker to creating a client with evidence-backed compatibility. No production modification is necessary to attempt validation once the environment exists.

### Continuation blocker disposition

All execution blockers listed above were cleared. The remaining items are design/contract warnings requiring human review before implementation, not blockers to completing Runtime Validation itself. No Step 02 work has begun.

## 14. Step 02 Readiness

### Historical result

The first Runtime Validation run ended **BLOCKED** because Python and uv were unavailable. Its evidence and unexecuted-check record are preserved throughout this document.

### Continuation result

The continuation completed the local environment, green test run, startup, live OpenAPI capture, GET/PATCH resolution, three-way comparison, and five live semantic-mode checks. Runtime Validation is complete.

Step 02 may be considered after human review, with these warnings carried forward:

- 12 material contract/runtime divergence groups remain;
- the static YAML loses GET asset under ordinary duplicate-key parsing;
- runtime OpenAPI has generic response and action-body schemas;
- dependencies are not locked and emitted one TestClient deprecation warning;
- authentication/tenant isolation and action persistence remain unresolved product/API risks;
- evaluation ground truth must remain isolated.

This classification authorizes no client, tool, agent, or Step 02 implementation by itself.

**READY_WITH_WARNINGS**
