# Information architecture — AI Investigation Platform

## Audience and primary workflow

The product is a working surface for the TRACTIAN Engineering Team. Its primary job is to let an engineer determine what the AI did, what it found, what supports its conclusion, why it stopped and what a person must do next. It is not a customer-facing chat.

## Navigation

The first delivery contains five operational areas:

1. **Overview** — workload, recent investigations, evidence posture and compact health indicators.
2. **Investigations** — dense searchable/filterable case table.
3. **Human Review** — safe-escalation queue and technical handoff inspection.
4. **Evaluations** — explicit empty placeholder for the future dual-judge contract; no scores are fabricated.
5. **System Health** — secondary provider/runtime telemetry, clearly marked as pilot mock data.

Investigation Detail is entered from Overview, Investigations or Human Review. It uses Trajectory, Evidence Ledger, Conclusion and Technical Report tabs to preserve context while controlling density.

## Core contracts mapped

The TypeScript view models in `frontend/lib/investigation-types.ts` mirror the backend vocabulary from:

- `api/app/investigation/state.py`: `InvestigationState`, `InvestigationDecision`, `ToolRequest`, `HumanHandoff` and terminal phases;
- `api/app/observability/models.py`: `TraceEvent` and `EvidenceRecord`;
- `api/app/intelligence/contracts.py`: `PlannerOutput`, `InvestigationConclusion`, `Claim` and `ReporterOutput`;
- `api/app/agents/understanding/schemas.py`: `UnderstandingOutput`.

The frontend does not change those sources or their semantics.

## Trace and trajectory

The trajectory is a chronological timeline of persisted operational events. It shows sequence, timestamp, event type, public summary, tool name and duration. It never renders chain-of-thought, private reasoning, scratchpads or internal monologue. Event inspection opens an accessible side sheet.

## Evidence Ledger and claim lineage

The ledger is a dense table with evidence ID, semantic status, tool/source, summary, HTTP transport and timestamp. Evidence inspection exposes the full lineage:

`Claim → EvidenceRecord → source_call_id → TraceEvent sequence → API source/path`.

The UI preserves the runtime distinction between a successful HTTP response and a semantically incomplete, inconclusive or conflicting result.

## Human Review

Safe escalation is presented as expected safety behavior rather than a generic error. The review sheet contains:

- investigation objectives attempted;
- evidence status counts;
- missing information;
- deterministic reason codes;
- unresolved point;
- suggested engineering continuation.

“Take review” remains disabled because the backend has no assignment/persistence contract.

## Typed integration mocks

`frontend/lib/mock-investigations.ts` contains three clearly labelled, deterministic scenarios:

- grounded completion with complete evidence, three claims, lineage and technical report;
- safe escalation with complete/inconclusive evidence and a human handoff;
- awaiting required information with no tool call, evidence or fabricated conclusion.

System-health numbers are also mock data and are labelled as such. Evaluations contain no fictitious result. These mocks must be replaced by an API adapter, not reshaped into a second domain model.

## Loading, empty, error and partial states

- Reusable loading skeletons exist for route-level loading.
- Filtered investigation results have an empty state.
- Evidence Ledger has a dedicated no-evidence state.
- Awaiting-information and safe-escalation cases render no fake claims.
- Partial/inconclusive evidence remains visible as semantic status.
- Runtime failures have a defined terminal-state treatment in the list and status system.

The initial static pilot does not yet receive network errors. The future API adapter should map transport failures into the existing error surface rather than changing domain status semantics.

## Responsive strategy

- **1440 px:** full 224 px navigation, multi-column operational surfaces and dense tables.
- **1280 px:** compact 190 px navigation and reduced content gutters.
- **1024 px:** icon navigation, stacked overview/detail columns and preserved table overflow.
- **Mobile:** bottom navigation, single-column content, horizontally scrollable technical tables and full-width inspection sheets.

## Integration boundary

The next frontend step is a typed read-only adapter that fetches investigations and their snapshots from the existing backend. It should validate payloads at the boundary, preserve raw identifiers/statuses, implement loading/error/retry states and keep ACTION capabilities unavailable. Review assignment, evaluation results and provider telemetry remain blocked until corresponding backend contracts exist.
