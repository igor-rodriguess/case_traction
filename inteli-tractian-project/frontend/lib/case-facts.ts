/**
 * Fatos derivados de uma investigação, para leitura humana.
 *
 * Tudo aqui é **calculado a partir do que já está no registro** — método HTTP,
 * estado semântico, limitações declaradas nas afirmações e no relatório. Nada é
 * inventado e nenhuma regra de negócio do backend é reimplementada: são
 * contagens e agrupamentos sobre dados que a investigação já produziu.
 */

import type { Evaluation } from './eval-types';
import type { Investigation, TraceEvent } from './investigation-types';

/** "1 registro" / "3 registros" — concordância correta, sem gambiarra no JSX. */
export const plural = (count: number, one: string, many: string): string =>
  `${count} ${count === 1 ? one : many}`;

export interface SecurityPosture {
  /** Somente-leitura verificado pelo método de cada consulta executada. */
  readOnly: boolean;
  readCount: number;
  writeCount: number;
  blocked: boolean;
  hardFailures: string[];
}

export function securityPosture(
  item: Investigation,
  evaluation?: Evaluation,
): SecurityPosture {
  const reads = item.evidence.filter((record) => record.method === 'GET');
  const writes = item.evidence.filter((record) => record.method !== 'GET');
  return {
    readOnly: writes.length === 0,
    readCount: reads.length,
    writeCount: writes.length,
    blocked: evaluation?.decision.final_verdict === 'REJECTED',
    hardFailures: evaluation?.decision.hard_failures ?? [],
  };
}

export interface Limitation {
  text: string;
  /** De onde a limitação veio, para o leitor saber que não é comentário editorial. */
  origin: string;
}

/**
 * Reúne as limitações que já estavam espalhadas — na ressalva de uma afirmação,
 * na seção de limitações do relatório e no estado degradado das evidências.
 */
export function limitations(item: Investigation): Limitation[] {
  const collected: Limitation[] = [];

  for (const claim of item.claims) {
    if (claim.limitation) {
      collected.push({ text: claim.limitation, origin: `Afirmação ${claim.claim_id}` });
    }
  }

  for (const text of item.report?.limitations ?? []) {
    if (!collected.some((entry) => entry.text === text)) {
      collected.push({ text, origin: 'Relatório técnico' });
    }
  }

  const degraded = item.evidence.filter((record) =>
    ['partial', 'inconclusive', 'unavailable', 'conflict'].includes(record.evidence_status),
  );
  for (const record of degraded) {
    collected.push({
      text: record.notes ?? record.summary,
      origin: `Evidência ${record.evidence_id} · ${record.evidence_status === 'unavailable' ? 'indisponível' : 'degradada'}`,
    });
  }

  for (const text of item.missing_information) {
    collected.push({ text, origin: 'Informação não fornecida na solicitação' });
  }

  return collected;
}

/** Consultas efetivamente executadas, na ordem em que concluíram. */
export function toolCalls(item: Investigation): TraceEvent[] {
  return item.trace.filter((event) => event.event_type === 'tool_completed');
}

/** A evidência que uma etapa da trajetória produziu, se produziu alguma. */
export function evidenceForEvent(item: Investigation, event: TraceEvent) {
  return item.evidence.find((record) => record.source_call_id === event.call_id);
}

/** Capacidades planejadas confrontadas com as que foram realmente usadas. */
export function capabilityUse(item: Investigation): { name: string; used: boolean }[] {
  const used = new Set(item.evidence.map((record) => record.tool_name));
  const planned = item.planned_capabilities.length
    ? item.planned_capabilities
    : [...used];
  return planned.map((name) => ({ name, used: used.has(name) }));
}
