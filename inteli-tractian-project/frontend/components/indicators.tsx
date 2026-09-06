/**
 * Indicadores de estado.
 *
 * Todos comunicam por **forma além de cor** — círculo com marca, losango,
 * quadrado, traço — para que a leitura não dependa de enxergar a diferença
 * entre laranja e vermelho.
 */

import type { EvidenceQuality, EvidenceStatus, TerminalState } from '@/lib/investigation-types';
import type { FinalVerdict } from '@/lib/eval-types';
import {
  evidenceQualityLabel,
  evidenceQualityTone,
  evidenceStatusLabel,
  finalVerdictLabel,
  finalVerdictTone,
  terminalStateLabel,
  terminalStateTone,
} from '@/lib/labels';

export function StateMark({ state }: { state: TerminalState }) {
  return (
    <span className={`mark mark--${terminalStateTone[state]}`}>
      <span className="mark__glyph" aria-hidden="true" />
      {terminalStateLabel[state]}
    </span>
  );
}

export function VerdictMark({ verdict }: { verdict: FinalVerdict }) {
  return (
    <span className={`mark mark--${finalVerdictTone[verdict]}`}>
      <span className="mark__glyph" aria-hidden="true" />
      {finalVerdictLabel[verdict]}
    </span>
  );
}

export function EvidenceMark({ status }: { status: EvidenceStatus }) {
  return (
    <span className={`ev-mark ev-mark--${status}`}>
      <span className="ev-mark__glyph" aria-hidden="true" />
      {evidenceStatusLabel[status]}
    </span>
  );
}

export function QualityMark({ quality }: { quality: EvidenceQuality }) {
  return (
    <span className={`q-mark q-mark--${evidenceQualityTone[quality]}`}>
      {evidenceQualityLabel[quality]}
    </span>
  );
}

/**
 * Qualidade das evidências com o detalhamento curto exigido pela leitura
 * técnica: nunca um percentual inventado, sempre contagens verificáveis.
 */
export function QualityReadout({
  quality,
  reasons,
}: {
  quality: EvidenceQuality;
  reasons: string[];
}) {
  return (
    <div className={`quality-readout quality-readout--${evidenceQualityTone[quality]}`}>
      <p className="quality-readout__head">
        <span className="label">Qualidade das evidências</span>
        <strong>{evidenceQualityLabel[quality]}</strong>
      </p>
      {reasons.length > 0 && (
        <ul className="quality-readout__list">
          {reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
