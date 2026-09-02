# Etapa 05 — Understanding Agent Baseline

Data: 2026-09-02

## Resultado

Foi implementada a fronteira determinística do Understanding Agent e o runner do baseline prompt-only. O componente transforma mensagem e contexto disponível em uma representação estruturada; ele não investiga, não chama tools, não acessa a API, não produz Evidence Records e não executa ACTIONs.

O código e as métricas estão prontos para um piloto no split sintético DEV. A execução com modelo real permanece corretamente bloqueada porque nenhum modelo/base, provider, credencial, orçamento ou política de retenção foi aprovado.

Classificação: **READY_FOR_MODEL_DECISION**.

## Escopo aprovado

O registro `datasets/approvals/synthetic-v1-understanding-pilot.json` autoriza o dataset sintético v1 somente para baseline e piloto do Understanding Agent. Permanecem proibidos uso em produção, execução de ACTIONs, fine-tuning do Investigator, tuning com holdout e treino com o Golden Set.

O registro `datasets/approvals/understanding-baseline-v1-decisions.json` documenta as decisões e divergências específicas desta etapa. Seu estado é `BLOCKED_MODEL_SELECTION`, com `external_api_calls_authorized=false`.

## Arquitetura

```text
synthetic DEV loader
        ↓
UnderstandingInput
        ↓
prompt v1 + JSON Schema estrito
        ↓
StructuredModelProvider
        ↓
UnderstandingOutput | invalid_output | provider_error
        ├── AgentInvocationLog
        └── métricas + artefatos do run
```

O provider é uma interface injetada. O agente não recebe `TractianClient`, registry, executor de tools ou Evidence Ledger. A instrumentação de modelo usa um registro irmão do Execution Trace porque uma invocação probabilística não é uma chamada de tool.

Não se registra chain-of-thought. Somente input, output estruturado final, timestamps, status, identificador do modelo, versão do prompt, latência, tokens e falha sanitizada entram no log.

## Contratos e dataset

Os modelos Pydantic espelham o schema aprovado com `extra="forbid"` e objetos congelados. `action_execution_allowed` é `Literal[False]`.

O loader valida a linha completa do JSONL, incluindo:

- `sample_id` e prefixo correspondente ao split;
- `schema_version="1.0"`;
- `schema_example_only=false`;
- enum do split;
- input e target estritos;
- tags e provenance;
- ausência de campos top-level extras;
- unicidade de `sample_id` dentro do arquivo.

Somente DEV está na allowlist do runner. Train e holdout são recusados antes de qualquer I/O. Os caminhos do Golden Set permanecem fora do runtime.

## Prompt-only baseline

O prompt `understanding_prompt_v1` contém instruções e vocabulário de áreas de investigação, sem exemplos do train, dev, holdout ou Golden. Ele proíbe diagnóstico, resposta ao cliente, tool call, trajetória de investigação, entidade inventada e execução de ação.

Os targets usam structured output estrito. Saída inválida não é corrigida silenciosamente e não recebe retry automático: ela é registrada como `invalid_output`. Falha do provider vira `provider_error` com mensagem sanitizada.

## Métricas

As métricas são determinísticas e calculadas somente para outputs válidos:

- schema valid/invalid/provider error;
- request class e matriz de confusão;
- quantidade e kinds de intents;
- decomposição de perguntas e dependências;
- precision, recall e F1 micro por bucket de entidades;
- F1 de investigation targets;
- missing information, reason code e blocking;
- detecção de ambiguidade;
- requested actions e flags;
- constraints por campo;
- erro absoluto de confidence;
- identificadores fabricados em entities e intent targets;
- investigation target com formato de tool call;
- violações de `action_execution_allowed`.

Textos livres como summary, requested outcome e redação da pergunta são declarados como não pontuados automaticamente. `confidence` é preservado por paridade com o schema, mas não é tratado como calibração ou gate de segurança.

## Artefatos

Uma execução válida grava fora de `datasets/`:

- `predictions.jsonl`;
- `metrics.json`;
- `run-manifest.json`;
- `errors.jsonl`;
- `showcase.json`;
- `agent-invocations.jsonl`.

O runner recusa destinos dentro de `datasets/`, `eval/` ou `agent-input/`. A sequência registrada nas predictions e no invocation log é monotônica e consistente.

O showcase declara categorias ausentes explicitamente e inclui casos ruins ou inválidos quando eles existem; não fabrica exemplos quando o baseline não foi executado.

## Estado do CLI

Comando previsto:

```powershell
cd api
.\.venv\Scripts\python.exe run_understanding_baseline.py
```

No estado atual, o comando retorna exit code 2, imprime `BLOCKED_MODEL_SELECTION` e grava somente um `run-manifest.json` com:

- `executions=0`;
- `external_api_calls=0`;
- nenhum modelo aprovado;
- predictions, metrics e showcase não produzidos;
- opções e procedimento explícito para desbloqueio.

Esse bloqueio é uma propriedade de segurança, não uma falha de implementação.

## Correções da revisão

A revisão posterior ao primeiro implementation pass corrigiu:

1. validação parcial do JSONL que descartava campos top-level;
2. `sequence=1` repetido nos registros anexados às predictions;
3. aceitação de `limit` zero ou negativo;
4. possibilidade de direcionar artefatos para áreas protegidas;
5. detecção de identificador fabricado limitada a `entities`, ignorando intent targets;
6. ausência de testes unitários isolados das métricas;
7. ausência do registro formal de decisões/divergências;
8. ausência desta documentação;
9. bytecode e caches Python aparecendo como arquivos não rastreados.

## Validação

Comandos executados sem API externa e com cache/bytecode desabilitados:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests/test_understanding_runner.py tests/test_understanding_metrics.py tests/test_understanding_agent.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Resultados:

| Escopo | Resultado |
|---|---:|
| Understanding dedicado | 82 passed |
| Regressão completa | 194 passed |
| Failed | 0 |
| Skipped | 0 |
| Warnings | 1 |

O único warning é `StarletteDeprecationWarning` no `fastapi.testclient`, relacionado à futura migração de `httpx` para `httpx2`. Nenhuma chamada externa foi realizada.

## Decisão necessária

Para executar o baseline real, o responsável pelo projeto ainda precisa escolher uma base/modelo e autorizar separadamente provider, credencial, orçamento, timeout e retenção/redação. A base deve permitir comparação justa com um eventual fine-tuning futuro.

Até essa decisão, não se deve definir `APPROVED_MODEL_BASE`, implementar fallback automático ou usar um modelo disponível apenas por conveniência.

**Final status: READY_FOR_MODEL_DECISION**
