export type TerminalState =
  | 'GROUNDED_COMPLETION'
  | 'SAFE_ESCALATION'
  | 'AWAITING_REQUIRED_INFORMATION'
  | 'FAILED';

export type EvidenceStatus =
  | 'complete'
  | 'partial'
  | 'inconclusive'
  | 'conflict'
  | 'unavailable';

export type EvidenceQuality = 'HIGH' | 'MEDIUM' | 'LOW' | 'INSUFFICIENT EVIDENCE';

export interface TraceEvent {
  trace_id: string;
  call_id: string;
  sequence: number;
  event_type: string;
  timestamp: string;
  tool_name?: string;
  duration_ms?: number;
  summary: string;
  details?: Record<string, string | number | boolean>;
}

export interface EvidenceRecord {
  evidence_id: string;
  trace_id: string;
  source_call_id: string;
  source_trace_sequence: number;
  sequence: number;
  collected_at: string;
  tool_name: string;
  client_operation: string;
  arguments: Record<string, string>;
  evidence_status: EvidenceStatus;
  transport_ok: boolean;
  status_code: number | null;
  method: string;
  path: string;
  summary: string;
  notes?: string;
  source: string;
}

export interface Claim {
  claim_id: string;
  statement: string;
  supporting_evidence_ids: string[];
  contradictory_evidence_ids: string[];
  limitation?: string;
  status: 'supported' | 'qualified' | 'contradicted' | 'unresolved';
}

export interface HumanHandoff {
  handoff_id: string;
  reason_codes: string[];
  evidence_ids: string[];
  missing_information: string[];
  suggested_next_step?: string;
}

export interface TechnicalReport {
  report_id: string;
  audience: 'tractian_engineering_team';
  executive_summary: string;
  investigation_performed: string[];
  findings: string[];
  evidence_references: string[];
  limitations: string[];
  missing_information: string[];
  suggested_engineer_next_steps: string[];
}

export interface Investigation {
  case_id: string;
  request_id: string;
  trace_id: string;
  asset_id: string;
  asset_name: string;
  company: string;
  request: string;
  request_class: 'investigate' | 'contextualize' | 'execute' | 'mixed' | 'unclear';
  entities: string[];
  investigation_targets: string[];
  missing_information: string[];
  plan_objectives: string[];
  planned_capabilities: string[];
  started_at: string;
  duration: string;
  terminal_state: TerminalState;
  evidence_quality: EvidenceQuality;
  evidence_quality_reasons: string[];
  unresolved_points: string[];
  trace: TraceEvent[];
  evidence: EvidenceRecord[];
  claims: Claim[];
  report?: TechnicalReport;
  human_handoff?: HumanHandoff;
  mock: true;
}

export type AppView =
  | 'overview'
  | 'investigations'
  | 'human-review'
  | 'evaluations'
  | 'system-health'
  | 'investigation-detail';
