-- =============================================================================
-- Persistência da investigação — schema inicial
--
-- Espelha os contratos Pydantic de `api/app/`:
--   InvestigationState · TraceEvent · EvidenceRecord · Claim ·
--   InvestigationConclusion · ReporterOutput · HumanHandoff ·
--   FinalEvaluationDecision · JudgeResult · JudgeAgreement · ArbitrationResult
--
-- Duas decisões estruturais que valem ser lidas antes do resto:
--
-- 1. A cadeia de proveniência é garantida por chave estrangeira, não por
--    convenção. `evidence_record` referencia `(run_id, source_trace_sequence)`
--    de `trace_event`, e `claim_evidence` liga afirmação a evidência. As hard
--    failures BROKEN_EVIDENCE_LINEAGE, CLAIM_WITHOUT_EVIDENCE e
--    EVIDENCE_REFERENCE_NOT_FOUND passam a ser impossíveis de persistir.
--
-- 2. O schema é `investigation`, não `public`. O PostgREST do Supabase expõe
--    apenas os schemas configurados, e este não está entre eles: o frontend não
--    alcança estas tabelas nem por engano. O caminho é
--    Frontend → API → camada de persistência → Supabase.
--
-- RLS fica ligada em todas as tabelas com política exclusiva de `service_role`.
-- `anon` e `authenticated` não recebem política alguma — negação por omissão.
-- =============================================================================

create schema if not exists investigation;

comment on schema investigation is
  'Persistência das investigações. Acesso apenas pela API de backend; não exposto via PostgREST.';

-- Valores espelhados dos enums Python. CHECK em vez de tipo ENUM: a lista muda
-- junto com o contrato, e alterar CHECK é uma migration simples.
create or replace function investigation.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

comment on function investigation.set_updated_at() is
  'Mantém updated_at sincronizado em qualquer UPDATE.';

-- -----------------------------------------------------------------------------
-- 1. Execução da investigação
-- -----------------------------------------------------------------------------

create table investigation.investigation_run (
  id                        uuid primary key default gen_random_uuid(),
  case_id                   text not null,
  request_id                text not null,
  trace_id                  text not null,

  company                   text,
  asset_id                  text,
  asset_name                text,

  request_message           text not null,
  request_context           jsonb not null default '{}'::jsonb,

  request_class             text
    check (request_class in ('investigate', 'contextualize', 'execute', 'mixed', 'unclear')),
  phase                     text not null default 'received',
  terminal_state            text
    check (terminal_state in (
      'GROUNDED_COMPLETION', 'SAFE_ESCALATION', 'AWAITING_REQUIRED_INFORMATION', 'FAILED'
    )),

  -- Contratos completos preservados. A leitura operacional usa as colunas
  -- acima; a auditoria usa o documento original, sem perda.
  understanding             jsonb,
  plan                      jsonb,

  understanding_source      text,
  planner_source            text,
  reporter_source           text,

  investigation_step_count  integer not null default 0 check (investigation_step_count >= 0),
  max_investigation_steps   integer not null default 8 check (max_investigation_steps >= 1),
  tool_call_count           integer not null default 0 check (tool_call_count >= 0),
  max_tool_calls            integer not null default 10 check (max_tool_calls >= 1),

  evidence_quality          text
    check (evidence_quality in ('HIGH', 'MEDIUM', 'LOW', 'INSUFFICIENT_EVIDENCE')),
  evidence_quality_reasons  text[] not null default '{}',

  error_code                text,
  error_summary             text,
  error_can_continue        boolean,

  started_at                timestamptz not null default now(),
  finished_at               timestamptz,
  duration_ms               integer check (duration_ms >= 0),

  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),

  constraint investigation_run_case_id_key unique (case_id),
  constraint investigation_run_trace_id_key unique (trace_id),
  -- Uma execução não termina antes de começar.
  constraint investigation_run_finished_after_started
    check (finished_at is null or finished_at >= started_at)
);

comment on table investigation.investigation_run is
  'Uma execução completa: solicitação, entendimento, plano e desfecho.';
comment on column investigation.investigation_run.understanding is
  'UnderstandingOutput original, preservado para auditoria.';
comment on column investigation.investigation_run.terminal_state is
  'Estado terminal da investigação. Não confundir com o veredicto da avaliação.';

create trigger investigation_run_set_updated_at
  before update on investigation.investigation_run
  for each row execute function investigation.set_updated_at();

create index investigation_run_terminal_state_idx
  on investigation.investigation_run (terminal_state);
create index investigation_run_started_at_idx
  on investigation.investigation_run (started_at desc);
create index investigation_run_asset_id_idx
  on investigation.investigation_run (asset_id)
  where asset_id is not null;

-- -----------------------------------------------------------------------------
-- 2. Trajetória (Trace)
-- -----------------------------------------------------------------------------

create table investigation.trace_event (
  id                uuid primary key default gen_random_uuid(),
  run_id            uuid not null
                      references investigation.investigation_run (id) on delete cascade,
  trace_id          text not null,
  call_id           text not null,
  sequence          integer not null check (sequence >= 1),

  event_type        text not null,
  occurred_at       timestamptz not null,

  tool_name         text,
  category          text,
  operation_kind    text,
  client_operation  text,

  arguments         jsonb not null default '{}'::jsonb,
  details           jsonb not null default '{}'::jsonb,
  duration_ms       numeric(12, 3) check (duration_ms >= 0),

  result            jsonb,
  failure           jsonb,

  created_at        timestamptz not null default now(),

  -- Alvo da chave estrangeira composta que sustenta a proveniência.
  constraint trace_event_run_sequence_key unique (run_id, sequence)
);

comment on table investigation.trace_event is
  'Evento operacional persistido. Nenhum campo de raciocínio interno é gravado aqui.';

create index trace_event_run_id_sequence_idx
  on investigation.trace_event (run_id, sequence);
create index trace_event_call_id_idx
  on investigation.trace_event (run_id, call_id);
create index trace_event_type_idx
  on investigation.trace_event (event_type);

-- -----------------------------------------------------------------------------
-- 3. Evidências
-- -----------------------------------------------------------------------------

create table investigation.evidence_record (
  id                     uuid primary key default gen_random_uuid(),
  run_id                 uuid not null
                           references investigation.investigation_run (id) on delete cascade,
  evidence_id            text not null,
  trace_id               text not null,
  source_call_id         text not null,
  source_trace_sequence  integer not null check (source_trace_sequence >= 1),
  sequence               integer not null check (sequence >= 1),

  collected_at           timestamptz not null,
  tool_name              text not null,
  client_operation       text not null,
  arguments              jsonb not null default '{}'::jsonb,

  evidence_status        text not null
    check (evidence_status in ('complete', 'partial', 'inconclusive', 'conflict', 'unavailable')),

  -- Transporte e semântica são medidos separadamente: uma resposta pode chegar
  -- com HTTP 200 e ainda assim ser inconclusiva.
  transport_ok           boolean not null,
  status_code            integer,
  method                 text not null,
  path                   text not null,

  data                   jsonb,
  notes                  text,

  created_at             timestamptz not null default now(),

  constraint evidence_record_run_evidence_key unique (run_id, evidence_id),
  constraint evidence_record_run_sequence_key unique (run_id, sequence),

  -- Proveniência garantida pelo banco: toda evidência nasce de um evento de
  -- trajetória da mesma execução.
  constraint evidence_record_lineage_fkey
    foreign key (run_id, source_trace_sequence)
    references investigation.trace_event (run_id, sequence)
    on delete cascade
);

comment on table investigation.evidence_record is
  'Registro de evidência com origem verificável. A FK composta impede lineage quebrada.';
comment on constraint evidence_record_lineage_fkey on investigation.evidence_record is
  'Impede persistir a hard failure BROKEN_EVIDENCE_LINEAGE.';

create index evidence_record_run_id_idx
  on investigation.evidence_record (run_id, sequence);
create index evidence_record_status_idx
  on investigation.evidence_record (evidence_status);
create index evidence_record_tool_idx
  on investigation.evidence_record (tool_name);

-- -----------------------------------------------------------------------------
-- 4. Conclusão e afirmações
-- -----------------------------------------------------------------------------

create table investigation.conclusion (
  id                 uuid primary key default gen_random_uuid(),
  run_id             uuid not null
                       references investigation.investigation_run (id) on delete cascade,
  conclusion_id      text not null,
  limitations        text[] not null default '{}',
  unresolved_points  text[] not null default '{}',
  reason_codes       text[] not null default '{}',
  created_at         timestamptz not null default now(),

  constraint conclusion_run_id_key unique (run_id)
);

comment on table investigation.conclusion is
  'Conclusão determinística da investigação. No máximo uma por execução.';

create table investigation.claim (
  id             uuid primary key default gen_random_uuid(),
  run_id         uuid not null
                   references investigation.investigation_run (id) on delete cascade,
  conclusion_pk  uuid not null
                   references investigation.conclusion (id) on delete cascade,
  claim_id       text not null,
  statement      text not null check (length(statement) > 0),
  status         text not null default 'supported'
    check (status in ('supported', 'qualified', 'contradicted', 'unresolved')),
  limitation     text,
  created_at     timestamptz not null default now(),

  constraint claim_run_claim_id_key unique (run_id, claim_id)
);

comment on table investigation.claim is
  'Afirmação da conclusão. Só existe atrelada a uma conclusão.';

create index claim_conclusion_idx on investigation.claim (conclusion_pk);

create table investigation.claim_evidence (
  claim_pk     uuid not null references investigation.claim (id) on delete cascade,
  evidence_pk  uuid not null references investigation.evidence_record (id) on delete cascade,
  relation     text not null
    check (relation in ('supporting', 'contradictory')),
  created_at   timestamptz not null default now(),

  primary key (claim_pk, evidence_pk, relation)
);

comment on table investigation.claim_evidence is
  'Liga afirmação a evidência. Uma referência a evidência inexistente é rejeitada pela FK.';

create index claim_evidence_evidence_idx on investigation.claim_evidence (evidence_pk);

-- -----------------------------------------------------------------------------
-- 5. Relatório técnico
-- -----------------------------------------------------------------------------

create table investigation.technical_report (
  id                             uuid primary key default gen_random_uuid(),
  run_id                         uuid not null
                                   references investigation.investigation_run (id) on delete cascade,
  report_id                      text not null,
  audience                       text not null default 'tractian_engineering_team'
    check (audience = 'tractian_engineering_team'),
  executive_summary              text not null,
  investigation_performed        text[] not null default '{}',
  findings                       text[] not null default '{}',
  evidence_references            text[] not null default '{}',
  contradictions                 text[] not null default '{}',
  limitations                    text[] not null default '{}',
  missing_information            text[] not null default '{}',
  suggested_engineer_next_steps  text[] not null default '{}',
  escalation_reason              text,
  created_at                     timestamptz not null default now(),

  constraint technical_report_run_id_key unique (run_id)
);

comment on table investigation.technical_report is
  'Relatório para a equipe de engenharia. A audiência é fixa por contrato.';

-- -----------------------------------------------------------------------------
-- 6. Encaminhamento humano
-- -----------------------------------------------------------------------------

create table investigation.human_handoff (
  id                   uuid primary key default gen_random_uuid(),
  run_id               uuid not null
                         references investigation.investigation_run (id) on delete cascade,
  handoff_id           text not null,
  reason_codes         text[] not null check (cardinality(reason_codes) >= 1),
  evidence_ids         text[] not null default '{}',
  missing_information  text[] not null default '{}',
  suggested_next_step  text,
  created_at           timestamptz not null default now(),

  constraint human_handoff_run_id_key unique (run_id)
);

comment on table investigation.human_handoff is
  'Encaminhamento para decisão humana, com o motivo obrigatoriamente declarado.';

-- -----------------------------------------------------------------------------
-- 7. Avaliação — decisão final
-- -----------------------------------------------------------------------------

create table investigation.evaluation (
  id                      uuid primary key default gen_random_uuid(),
  run_id                  uuid not null
                            references investigation.investigation_run (id) on delete cascade,
  evaluation_id           text not null,
  eval_run_id             text not null,

  final_verdict           text not null
    check (final_verdict in (
      'APPROVED', 'APPROVED_WITH_WARNINGS', 'HUMAN_REVIEW_REQUIRED', 'REJECTED'
    )),
  approved                boolean not null,
  human_review_required   boolean not null,
  recommended_action      text not null
    check (recommended_action in (
      'PROCEED', 'PROCEED_WITH_WARNINGS', 'ENGINEERING_REVIEW', 'BLOCK_RESULT'
    )),

  overall_score           numeric(4, 2) not null check (overall_score >= 0 and overall_score <= 4),
  overall_score_max       numeric(4, 2) not null default 4,

  agreement_level         text not null check (agreement_level in ('HIGH', 'MEDIUM', 'LOW')),
  hard_failures           text[] not null default '{}',
  arbitration_used        boolean not null default false,

  judge_a_verdict         text not null
    check (judge_a_verdict in ('PASS', 'PASS_WITH_WARNINGS', 'FAIL', 'HUMAN_REVIEW_REQUIRED')),
  judge_b_verdict         text not null
    check (judge_b_verdict in ('PASS', 'PASS_WITH_WARNINGS', 'FAIL', 'HUMAN_REVIEW_REQUIRED')),

  barema_version          text not null,
  headline                text not null,
  evaluated_at            timestamptz not null default now(),
  created_at              timestamptz not null default now(),

  constraint evaluation_run_id_key unique (run_id),
  constraint evaluation_evaluation_id_key unique (evaluation_id),

  -- A política final do backend nunca aprova com hard failure. O banco recusa
  -- a linha que contradiga isso.
  constraint evaluation_hard_failure_blocks_approval
    check (cardinality(hard_failures) = 0 or approved = false),
  -- APPROVED e aprovação são a mesma informação vista de dois ângulos.
  constraint evaluation_verdict_matches_approval
    check (
      (final_verdict in ('APPROVED', 'APPROVED_WITH_WARNINGS') and approved)
      or (final_verdict in ('HUMAN_REVIEW_REQUIRED', 'REJECTED') and not approved)
    )
);

comment on table investigation.evaluation is
  'Decisão final da FinalEvaluationPolicy. Persistida como veio; nunca recalculada.';
comment on constraint evaluation_hard_failure_blocks_approval on investigation.evaluation is
  'Uma condição crítica reprova sozinha: aprovar com hard failure é impossível.';

create index evaluation_final_verdict_idx on investigation.evaluation (final_verdict);
create index evaluation_review_idx
  on investigation.evaluation (human_review_required)
  where human_review_required;

create table investigation.evaluation_critical_score (
  evaluation_pk  uuid not null references investigation.evaluation (id) on delete cascade,
  criterion      text not null,
  score          smallint not null check (score between 0 and 4),
  meets_minimum  boolean not null,

  primary key (evaluation_pk, criterion)
);

comment on table investigation.evaluation_critical_score is
  'Notas dos critérios de peso alto, como o backend as consolidou.';

create table investigation.evaluation_finding (
  id             uuid primary key default gen_random_uuid(),
  evaluation_pk  uuid not null references investigation.evaluation (id) on delete cascade,
  kind           text not null check (kind in ('warning', 'review_reason')),
  code           text not null,
  detail         text not null,
  criterion      text,
  created_at     timestamptz not null default now()
);

comment on table investigation.evaluation_finding is
  'Ressalvas e motivos de revisão. `kind` separa os dois sem duplicar tabela.';

create index evaluation_finding_evaluation_idx
  on investigation.evaluation_finding (evaluation_pk, kind);

-- -----------------------------------------------------------------------------
-- 8. Avaliadores
-- -----------------------------------------------------------------------------

create table investigation.judge_result (
  id                       uuid primary key default gen_random_uuid(),
  evaluation_pk            uuid not null references investigation.evaluation (id) on delete cascade,
  judge_id                 text not null check (judge_id in ('judge_a', 'judge_b')),

  verdict                  text not null
    check (verdict in ('PASS', 'PASS_WITH_WARNINGS', 'FAIL', 'HUMAN_REVIEW_REQUIRED')),
  overall_score            numeric(4, 2) not null check (overall_score >= 0 and overall_score <= 4),
  confidence_in_evaluation text not null check (confidence_in_evaluation in ('HIGH', 'MEDIUM', 'LOW')),
  needs_human_review       boolean not null default false,

  hard_failures            text[] not null default '{}',
  strengths                text[] not null default '{}',
  weaknesses               text[] not null default '{}',
  evidence_references      text[] not null default '{}',

  provider                 text,
  model                    text,
  created_at               timestamptz not null default now(),

  constraint judge_result_evaluation_judge_key unique (evaluation_pk, judge_id)
);

comment on table investigation.judge_result is
  'Resultado estruturado de um avaliador. Nenhum campo de raciocínio interno é persistido.';

create table investigation.judge_criterion_score (
  judge_pk             uuid not null references investigation.judge_result (id) on delete cascade,
  criterion            text not null,
  score                smallint not null check (score between 0 and 4),
  reason               text not null default '',
  evidence_references  text[] not null default '{}',

  primary key (judge_pk, criterion),

  -- Espelha a validação do contrato: crítica severa em critério de evidência
  -- exige apontar a evidência que a sustenta.
  constraint judge_criterion_low_score_needs_reference
    check (
      score > 2
      or criterion not in ('EVIDENCE_GROUNDING', 'EVIDENCE_PROVENANCE')
      or cardinality(evidence_references) >= 1
    )
);

comment on table investigation.judge_criterion_score is
  'Nota por critério. Crítica severa a grounding exige referência de evidência.';

-- -----------------------------------------------------------------------------
-- 9. Concordância e arbitragem
-- -----------------------------------------------------------------------------

create table investigation.judge_agreement (
  id                   uuid primary key default gen_random_uuid(),
  evaluation_pk        uuid not null references investigation.evaluation (id) on delete cascade,
  agreement_level      text not null check (agreement_level in ('HIGH', 'MEDIUM', 'LOW')),
  verdict_match        boolean not null,
  hard_failure_match   boolean not null,
  mean_absolute_delta  numeric(4, 2) not null check (mean_absolute_delta >= 0),
  max_delta            smallint not null check (max_delta between 0 and 4),
  arbitration_required boolean not null default false,
  rationale            text not null,
  created_at           timestamptz not null default now(),

  constraint judge_agreement_evaluation_key unique (evaluation_pk)
);

comment on table investigation.judge_agreement is
  'Comparação entre os dois avaliadores, calculada de forma determinística.';

create table investigation.judge_disagreement (
  agreement_pk   uuid not null references investigation.judge_agreement (id) on delete cascade,
  criterion      text not null,
  judge_a_score  smallint not null check (judge_a_score between 0 and 4),
  judge_b_score  smallint not null check (judge_b_score between 0 and 4),
  delta          smallint not null check (delta between 1 and 4),

  primary key (agreement_pk, criterion),

  -- Divergência registrada é divergência real.
  constraint judge_disagreement_delta_matches_scores
    check (delta = abs(judge_a_score - judge_b_score))
);

comment on table investigation.judge_disagreement is
  'Critério em que os avaliadores divergiram, com a diferença conferida pelo banco.';

create table investigation.arbitration (
  id                   uuid primary key default gen_random_uuid(),
  evaluation_pk        uuid not null references investigation.evaluation (id) on delete cascade,
  arbitrated_criteria  text[] not null check (cardinality(arbitrated_criteria) >= 1),
  resolved             boolean not null,
  note                 text not null,
  created_at           timestamptz not null default now(),

  constraint arbitration_evaluation_key unique (evaluation_pk)
);

comment on table investigation.arbitration is
  'Rodada única de arbitragem sobre os critérios divergentes.';

-- =============================================================================
-- Row Level Security
--
-- Ligada em todas as tabelas. Apenas `service_role` recebe política — o backend
-- usa essa credencial. `anon` e `authenticated` ficam sem nenhuma política, o
-- que em RLS significa negação total.
-- =============================================================================

do $$
declare
  t text;
begin
  foreach t in array array[
    'investigation_run', 'trace_event', 'evidence_record', 'conclusion',
    'claim', 'claim_evidence', 'technical_report', 'human_handoff',
    'evaluation', 'evaluation_critical_score', 'evaluation_finding',
    'judge_result', 'judge_criterion_score', 'judge_agreement',
    'judge_disagreement', 'arbitration'
  ]
  loop
    execute format('alter table investigation.%I enable row level security', t);
    execute format('alter table investigation.%I force row level security', t);
    execute format(
      'create policy %I on investigation.%I for all to service_role using (true) with check (true)',
      t || '_service_role_all', t
    );
  end loop;
end;
$$;

-- Nenhum privilégio para os papéis públicos: o frontend não alcança o schema.
revoke all on schema investigation from anon, authenticated;
revoke all on all tables in schema investigation from anon, authenticated;

grant usage on schema investigation to service_role;
grant all on all tables in schema investigation to service_role;
grant all on all sequences in schema investigation to service_role;

alter default privileges in schema investigation
  grant all on tables to service_role;
alter default privileges in schema investigation
  grant all on sequences to service_role;
