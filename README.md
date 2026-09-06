# TRACTIAN AI Investigation Console

Agente de investigação para monitoramento de condição industrial: recebe uma dúvida técnica,
investiga consultando a API industrial **somente por leitura**, conclui apenas o que a evidência
sustenta, e é avaliado por dois julgadores independentes antes de qualquer resultado ser tratado
como resposta.

> O briefing original do desafio está em [`STUDENT-GUIDE.md`](./inteli-tractian-project/STUDENT-GUIDE.md) e o material-base
> em [`docs/`](./inteli-tractian-project/docs/).

## A ideia central

O sistema não foi construído para acertar sempre. Foi construído para que **seja possível verificar
se acertou** — e para parar quando não sabe.

```text
Solicitação
  → Understanding      interpreta, extrai entidades, aponta o que falta
  → Planner            define objetivos e capacidades de leitura autorizadas
  → Investigator       escolhe a ferramenta (nunca executa)
  → Tool Executor      executa e registra (o agente não escolhe o que é auditado)
  → Trace + Evidence   trajetória e proveniência
  → Completion Policy  decide de forma determinística se há evidência suficiente
  → Conclusão          uma afirmação por evidência, montada do que foi observado
  → Reporter           relatório técnico para engenharia
  → Judge A + Judge B  avaliam contra um barema versionado
  → Agreement          compara; arbitra uma vez se divergirem
  → FinalEvaluationPolicy  produz a decisão operacional
```

Quatro garantias que não dependem do modelo se comportar bem:

- **Nenhuma ação de escrita é possível.** Só existem READ tools no registry.
- **Proveniência é chave estrangeira, não convenção.** Evidência sem evento de trajetória
  correspondente é recusada pelo banco.
- **O agente não decide se foi aprovado.** Quem avalia é o Eval; quem resolve é a política final.
- **Raciocínio interno não é persistido.** Só metadado operacional entra na trajetória.

## Estrutura

Todo o projeto vive em [`inteli-tractian-project/`](./inteli-tractian-project/); os caminhos
abaixo são relativos a ele.

| Pasta | O que é |
| :--- | :--- |
| `api/app/agents`, `intelligence`, `investigation` | Agentes e contratos Pydantic |
| `api/app/tools` | READ tools e registry autorizado |
| `api/app/observability` | Trace, Evidence Ledger, executor instrumentado |
| `api/app/eval` | Barema, Judges, concordância, arbitragem, política final |
| `api/app/application` | Pipeline real e serviço de ciclo de vida |
| `api/app/persistence` | Repositório e persistência progressiva |
| `api/app/console_api.py` | API do console, sob `/api/v1` |
| `api/app/main.py` | API industrial simulada (a fonte que as tools consultam) |
| `frontend/` | Console em vinext + React + TypeScript |
| `supabase/migrations/` | Schema versionado |
| `docs/` | Decisões e validações de cada etapa |

## Como rodar

Requisitos: Python 3.10+, Node 22+, e um projeto Supabase.

### 1. Configurar o ambiente

```bash
cd inteli-tractian-project
cp api/.env.example api/.env
```

Preencha em `api/.env`:

| Variável | Para quê |
| :--- | :--- |
| `GROQ_API_KEY`, `GEMINI_API_KEY` | Provedores dos agentes |
| `GROQ_INVESTIGATOR_MODEL`, `GEMINI_UNDERSTANDING_MODEL`, `GEMINI_PLANNER_MODEL` | Modelos por papel |
| `SUPABASE_DB_URL` | Conexão PostgreSQL usada pela persistência |
| `JUDGE_A_PROVIDER`, `JUDGE_B_PROVIDER` | Provedores dos avaliadores (opcional) |

`api/.env` não é versionado. Nenhuma credencial vai para o frontend: ele fala com a API, nunca com
o banco.

### 2. Instalar e aplicar a migration

```bash
cd api && python -m venv .venv && .venv/bin/pip install -e ".[dev]" psycopg[binary] python-dotenv
cd ..
python api/scripts/apply_migrations.py
python api/scripts/verify_schema.py     # confere o banco real, não o exit code
```

`verify_schema.py` existe porque migration retornando zero não prova nada: ele lê o catálogo do
Postgres e falha se faltar tabela, constraint, RLS ou policy.

### 3. Subir o backend

```bash
cd api && .venv/bin/python -m uvicorn app.main:app --port 8000
```

Duas superfícies no mesmo processo: a API industrial simulada na raiz (`/assets`, `/analyses`, …),
que é o que as tools consultam, e o console em `/api/v1`.

```bash
curl http://127.0.0.1:8000/api/v1/health
# {"api":"healthy","database":"connected", ...}
```

### 4. Subir o frontend

```bash
cd frontend && npm install && npm run dev
```

Abra <http://localhost:3000>. Se a API estiver fora do ar, a interface diz isso — não existe queda
para dados falsos.

### 5. Criar uma investigação

Pela interface: **Nova investigação** → descreva a dúvida → **Iniciar investigação**.

O `POST` responde `202` com o identificador e a execução segue em segundo plano; a página acompanha
por polling e para quando o caso chega a um desfecho. A fase mostrada é a que o backend registrou —
nenhum percentual é inventado.

Pela API:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/investigations \
  -H "Content-Type: application/json" \
  -d '{"message":"Qual o contexto atual do ativo asset_C710 e o que o RMS mostra?"}'
```

## Endpoints do console

```text
POST /api/v1/investigations              cria e inicia          → 202
GET  /api/v1/investigations              lista
GET  /api/v1/investigations/{id}         dossiê consolidado
GET  /api/v1/investigations/{id}/trace
GET  /api/v1/investigations/{id}/evidence
GET  /api/v1/investigations/{id}/evaluation
GET  /api/v1/investigations/{id}/human-review
GET  /api/v1/review-queue
GET  /api/v1/health
```

## Persistência progressiva

Gravar tudo numa transação só protegia a integridade, mas tornava a execução invisível até o fim —
e uma falha tardia apagaria a trajetória já vivida. A atomicidade mudou de granularidade sem
afrouxar nada: cada checkpoint é uma transação que fecha uma unidade que faz sentido sozinha.

```text
solicitação recebida     run                                  commit
entendimento concluído   run + eventos                        commit
plano criado             run + eventos                        commit
consulta executada       evento + evidências que ela gerou    commit
conclusão produzida      conclusão + afirmações + vínculos    commit
relatório gerado         relatório                            commit
avaliação concluída      decisão + avaliadores + divergências commit
```

A evidência nasce no mesmo commit do evento que a originou, então a chave estrangeira composta que
garante a proveniência nunca fica pendurada. Uma investigação interrompida no meio é um registro de
auditoria válido, não lixo.

## Verificação

A partir de `inteli-tractian-project/`:

```bash
(cd api && .venv/bin/python -m pytest -q)                            # 499 testes
(cd frontend && npm run typecheck && npm run lint && npm run build)
python api/scripts/run_console_e2e.py                                # E2E real, sem Golden e sem mock
```

`run_console_e2e.py` executa uma investigação de verdade e depois audita o banco: compara chamadas
de ferramenta executadas contra persistidas, e verifica órfãos e lineage.

## Limitações conhecidas

1. **Execução in-process.** Adequada para demonstração e instância única. Se o processo reiniciar no
   meio, o que já foi persistido permanece e o caso fica sem estado terminal — visivelmente. Um
   worker durável é evolução futura.
2. **Avaliação sujeita a timeout do provedor.** A entrada dos Judges é grande; em execuções longas o
   Eval pode não completar. O caso fica registrado sem avaliação, e a interface mostra isso.
3. **Atribuição de revisor não existe.** Não há workflow de posse no backend, e a interface não
   simula um.
4. **Golden set nunca executado em runtime.** É referência de avaliação, isolada por guarda
   explícita.
5. **Mobile não é prioridade.** Abaixo de 1024 px o layout degrada, mas não quebra.
