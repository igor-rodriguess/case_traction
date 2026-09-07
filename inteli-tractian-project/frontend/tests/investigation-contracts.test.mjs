import assert from 'node:assert/strict';
import test from 'node:test';
import { investigations } from './fixtures/mock-investigations.ts';

const terminalStates = new Set(['GROUNDED_COMPLETION', 'SAFE_ESCALATION', 'AWAITING_REQUIRED_INFORMATION', 'FAILED']);
const evidenceStatuses = new Set(['complete', 'partial', 'inconclusive', 'conflict', 'unavailable']);

test('contains the three required navigable investigation scenarios', () => {
  assert.ok(investigations.length >= 3);
  const availableStates = new Set(investigations.map((item) => item.terminal_state));
  for (const requiredState of ['GROUNDED_COMPLETION', 'SAFE_ESCALATION', 'AWAITING_REQUIRED_INFORMATION']) {
    assert.ok(availableStates.has(requiredState));
  }
});

test('uses only backend terminal and evidence status values', () => {
  for (const investigation of investigations) {
    assert.ok(terminalStates.has(investigation.terminal_state));
    for (const evidence of investigation.evidence) assert.ok(evidenceStatuses.has(evidence.evidence_status));
  }
});

test('every evidence record preserves tool-call and trace lineage', () => {
  for (const investigation of investigations) {
    for (const evidence of investigation.evidence) {
      const sourceEvent = investigation.trace.find((event) => event.call_id === evidence.source_call_id && event.sequence === evidence.source_trace_sequence);
      assert.ok(sourceEvent, `${evidence.evidence_id} must resolve to a persisted trace event`);
      assert.equal(evidence.trace_id, investigation.trace_id);
      assert.ok(evidence.tool_name);
      assert.ok(evidence.source);
    }
  }
});

test('grounded claims reference only known evidence records', () => {
  for (const investigation of investigations) {
    const ids = new Set(investigation.evidence.map((evidence) => evidence.evidence_id));
    for (const claim of investigation.claims) {
      for (const evidenceId of [...claim.supporting_evidence_ids, ...claim.contradictory_evidence_ids]) assert.ok(ids.has(evidenceId));
    }
  }
});

test('safe escalation has a human handoff and no fabricated conclusion', () => {
  const escalation = investigations.find((item) => item.terminal_state === 'SAFE_ESCALATION');
  assert.ok(escalation?.human_handoff);
  assert.equal(escalation.claims.length, 0);
  assert.ok(escalation.unresolved_points.length > 0);
});

test('awaiting-information case calls no tool and fabricates no evidence', () => {
  const awaiting = investigations.find((item) => item.terminal_state === 'AWAITING_REQUIRED_INFORMATION');
  assert.ok(awaiting);
  assert.equal(awaiting.evidence.length, 0);
  assert.equal(awaiting.claims.length, 0);
  assert.equal(awaiting.trace.some((event) => event.event_type.startsWith('tool_')), false);
});

test('evidence quality is qualitative and never an invented percentage', () => {
  for (const investigation of investigations) {
    assert.match(investigation.evidence_quality, /^(HIGH|MEDIUM|LOW|INSUFFICIENT EVIDENCE)$/);
    assert.doesNotMatch(investigation.evidence_quality, /%/);
  }
});
