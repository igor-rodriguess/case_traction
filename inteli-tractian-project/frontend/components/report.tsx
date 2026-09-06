/**
 * Relatório técnico — tratado como documento, não como coleção de cartões.
 *
 * A estrutura segue a de um relatório de engenharia: resumo, o que foi feito,
 * constatações, evidências citadas, limitações, pontos abertos e o próximo
 * passo. Sem caixa em volta de cada seção; a hierarquia é tipográfica.
 */

import type { Investigation, EvidenceRecord } from '@/lib/investigation-types';

interface Props {
  item: Investigation;
  onInspectEvidence: (record: EvidenceRecord) => void;
}

function ReportBlock({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <section className="doc__block">
      <h3>{title}</h3>
      <ul>
        {items.map((text) => (
          <li key={text}>{text}</li>
        ))}
      </ul>
    </section>
  );
}

export function TechnicalReport({ item, onInspectEvidence }: Props) {
  const report = item.report;
  if (!report) {
    return (
      <div className="notice">
        <p className="notice__title">Nenhum relatório foi produzido</p>
        <p>
          O relatório técnico só é gerado quando a investigação chega a uma conclusão ou a um
          encaminhamento com evidência preservada.
        </p>
        <dl className="notice__facts">
          <div>
            <dt>Estado</dt>
            <dd>Não produzido</dd>
          </div>
          <div>
            <dt>Impacto</dt>
            <dd>
              Não há documento para encaminhar ao cliente. As evidências coletadas seguem
              disponíveis na seção Trajetória e evidências.
            </dd>
          </div>
        </dl>
      </div>
    );
  }

  return (
    <article className="doc">
      <header className="doc__head">
        <div>
          <p className="label">Preparado para</p>
          <p className="doc__audience">Equipe de Engenharia TRACTIAN</p>
        </div>
        <p className="doc__id mono">{report.report_id}</p>
      </header>

      <section className="doc__block">
        <h3>Resumo</h3>
        <p className="doc__lead">{report.executive_summary}</p>
      </section>

      <div className="doc__columns">
        <div>
          <ReportBlock title="O que foi investigado" items={report.investigation_performed} />
          <ReportBlock title="Principais constatações" items={report.findings} />
        </div>
        <div>
          <ReportBlock title="Limitações" items={report.limitations} />
          <ReportBlock title="Pontos ainda não resolvidos" items={item.unresolved_points} />
          <ReportBlock
            title="Próximo passo recomendado"
            items={report.suggested_engineer_next_steps}
          />
        </div>
      </div>

      {report.evidence_references.length > 0 && (
        <footer className="doc__refs">
          <p className="label">Evidências citadas</p>
          <p>
            {report.evidence_references.map((id) => {
              const record = item.evidence.find((entry) => entry.evidence_id === id);
              if (!record) return null;
              return (
                <button
                  key={id}
                  type="button"
                  className="link-button mono"
                  onClick={() => onInspectEvidence(record)}
                >
                  {id}
                </button>
              );
            })}
          </p>
        </footer>
      )}
    </article>
  );
}
