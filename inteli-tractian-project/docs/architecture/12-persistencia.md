# Persistência da investigação (Supabase / PostgreSQL)

Primeira etapa de persistência real. O schema é versionado em migrations, o
acesso é exclusivo do backend, e o banco carrega as mesmas garantias que os
contratos Pydantic — não como documentação, como constraint.

## Configuração

Todas as variáveis já existiam no ambiente. Nenhuma foi criada, nenhum projeto
novo foi provisionado.

| Variável | Papel |
|---|---|
| `SUPABASE_URL` | Endereço do projeto |
| `SUPABASE_PUBLISHABLE_KEY` | Chave pública; **não usada** por este produto |
| `SUPABASE_SECRET_KEY` | Credencial de backend |
| `SUPABASE_JWKS_URL` | Verificação de token, para quando houver autenticação |
| `SUPABASE_DB_URL` | Conexão PostgreSQL usada pela camada de persistência |

`api/.env` continua fora do Git. `api/.env.example` lista apenas os nomes.

## Por que um schema próprio

As tabelas vivem em `investigation`, não em `public`. O PostgREST do Supabase
expõe somente os schemas configurados, e este não está entre eles — o frontend
não alcança as tabelas nem por engano. O caminho é único:

```
Frontend → API → camada de persistência → Supabase
```

RLS está ligada e forçada nas 16 tabelas. A única política é de `service_role`.
`anon` e `authenticated` não recebem política nenhuma, o que em RLS significa
negação total, e também não recebem privilégio de tabela.

## Garantias que o banco recusa violar

A decisão que mais importa aqui: a proveniência deixou de ser convenção.

| Garantia | Mecanismo | Hard failure que passa a ser impossível |
|---|---|---|
| Evidência nasce de um evento da trajetória | FK composta `(run_id, source_trace_sequence)` → `trace_event(run_id, sequence)` | `BROKEN_EVIDENCE_LINEAGE` |
| Afirmação cita evidência existente | `claim_evidence` com FK para `evidence_record` | `EVIDENCE_REFERENCE_NOT_FOUND` |
| Condição crítica reprova sozinha | `check (cardinality(hard_failures) = 0 or approved = false)` | aprovar com `hard_failure` |
| Veredicto e aprovação não divergem | `check` cruzando `final_verdict` e `approved` | `REJECTED` marcado como aprovado |
| Divergência registrada é real | `check (delta = abs(judge_a_score - judge_b_score))` | divergência inventada |
| Crítica severa a grounding cita evidência | `check` em `judge_criterion_score` | crítica sem lastro |
| Nota dentro da escala do barema | `check (score between 0 and 4)` | nota fora da escala |
| Execução não termina antes de começar | `check (finished_at >= started_at)` | relógio andando para trás |
| Encaminhamento declara o motivo | `check (cardinality(reason_codes) >= 1)` | handoff mudo |
| Relatório tem a audiência contratada | `check (audience = 'tractian_engineering_team')` | relatório para outro público |

Todas foram verificadas por comportamento, não por inspeção: `11/11` tentativas
de gravar violação foram recusadas pelo Postgres, cada uma com o `SQLSTATE`
correspondente.

## Tabelas

```
investigation_run ──┬─ trace_event ──┐
                    ├─ evidence_record ◄┘ (FK composta: lineage)
                    ├─ conclusion ── claim ── claim_evidence ─► evidence_record
                    ├─ technical_report
                    ├─ human_handoff
                    └─ evaluation ──┬─ evaluation_critical_score
                                    ├─ evaluation_finding (warning | review_reason)
                                    ├─ judge_result ── judge_criterion_score
                                    ├─ judge_agreement ── judge_disagreement
                                    └─ arbitration
```

16 tabelas · 16 PKs · 18 FKs · 14 UNIQUE · 43 CHECK · 44 índices.

`understanding` e `plan` ficam guardados também como `jsonb`: a leitura
operacional usa as colunas tipadas, e a auditoria mantém o contrato original sem
perda.

## Migrations

```
supabase/migrations/20260906120000_initial_investigation_persistence.sql
```

Aplicadas por `api/scripts/apply_migrations.py`, que usa a mesma tabela de
controle do Supabase CLI (`supabase_migrations.schema_migrations`) — o histórico
continua legível por qualquer ferramenta oficial. Cada migration roda em
transação própria: aplica inteira ou não aplica.

```bash
python api/scripts/apply_migrations.py --status   # lista pendentes
python api/scripts/apply_migrations.py            # aplica
python api/scripts/verify_schema.py               # confere o banco real
```

`verify_schema.py` existe porque exit code zero não é prova. Ele lê o catálogo do
Postgres e falha se faltar tabela, PK, constraint nomeada, RLS ou policy — ou se
algum papel público tiver ganhado privilégio.

## Camada de persistência

`api/app/persistence/` é a única fronteira com o banco.

- `settings.py` lê a configuração do ambiente. Nunca aceita credencial por
  argumento, e o `__repr__` de `DatabaseSettings` mascara a URL para que um log
  distraído não vaze a senha.
- `repository.py` grava a investigação inteira numa transação. Um caso meio
  gravado é pior que caso nenhum, porque a proveniência aparenta estar íntegra
  quando não está.

A ordem de escrita não é arbitrária: trajetória antes das evidências, conclusão
antes das afirmações, avaliação antes dos avaliadores — é o que as chaves
estrangeiras exigem.

Leitura: `list_investigations()`, `get_investigation(case_id)` e
`review_queue()`, esta última com a mesma regra que a interface já usa
(encaminhamento humano, revisão exigida, ou `REJECTED`).

## Verificação

`api/tests/test_persistence_roundtrip.py` — 7 testes contra o banco real, que
pulam quando `SUPABASE_DB_URL` não está no ambiente. Gravam, leem de volta,
conferem que a proveniência sobreviveu, e apagam o caso ao final.

Três deles verificam recusa, não sucesso: evidência citada inexistente, evidência
sem evento de trajetória, e aprovação com condição crítica. Nos três, a transação
inteira volta atrás — nem a execução fica no banco.

Suíte completa: **490 testes passando**. Banco sem resíduo após a execução.

## O que não foi feito

Nenhum endpoint novo, nenhuma escrita a partir do frontend, nenhuma migração dos
mocks da interface para o banco. O frontend segue com dados simulados; a troca é
a próxima etapa, e é local: substituir `mock-investigations.ts` e
`mock-evaluations.ts` por um cliente da API. Os componentes não mudam, porque
consomem os tipos e não os mocks.
