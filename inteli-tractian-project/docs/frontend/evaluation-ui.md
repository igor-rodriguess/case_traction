# Frontend — camada de avaliação (Etapa 11)

Documento complementar a `ui-foundations.md` e `information-architecture.md`. Registra o que foi acrescentado quando o Eval passou a existir de verdade no backend.

## O que já existia e foi preservado

A auditoria classificou o frontend anterior como majoritariamente **KEEP**. Nenhum rewrite foi feito.

| Área | Decisão |
|---|---|
| Stack (vinext + React 19 + TypeScript + Tailwind v4 + shadcn) | KEEP — build, lint e typecheck limpos |
| Tokens (slate/blue, Inter + Inter Tight, radius 2–8px) | KEEP — já industrial e deliberadamente pouco arredondado |
| Design system BEM em `globals.css` | KEEP — evita sopa de utilitários no markup |
| Tipos espelhando contratos do backend | KEEP |
| Navegação de cinco views | KEEP |
| `loading.tsx` / `error.tsx` | KEEP |
| Camada de Eval | **MISSING** — construída nesta etapa |
| Claim lineage navegável | **MISSING** — construída nesta etapa |

O status já era comunicado por **forma** além de cor (círculo com check, losango, tracejado), o que satisfaz acessibilidade sem retrabalho.

## Contratos

`lib/eval-types.ts` espelha `api/app/eval/` literalmente: `FinalEvaluationDecision`, `JudgeResult`, `JudgeAgreement`, `ArbitrationResult`, `Criterion`, `Score`, `WarningCode`, `ReviewReasonCode`, `RecommendedAction`, `HardFailure`.

**O frontend não recalcula regra de negócio.** `approved`, `human_review_required`, `recommended_action` e `headline` chegam decididos pela `FinalEvaluationPolicy`. A interface renderiza.

## Estado terminal ≠ veredicto do Eval

A distinção mais fácil de confundir, e por isso explicitada em três lugares: colunas separadas na lista de Evaluations, legenda `Terminal state and evaluation verdict are separate judgements` no detalhe, e um caso mockado que a demonstra — `CASE-2026-0416` conclui com `GROUNDED_COMPLETION` e ainda assim recebe `HUMAN_REVIEW_REQUIRED`, porque a investigação conseguiu concluir mas a avaliação não aprovou o trabalho automaticamente.

## Hierarquia da tela de Evaluation

Ordem deliberada, do que decide para o que explica:

1. **Decisão final** — veredicto, nota sobre 4, ação recomendada
2. **Critérios críticos** — os de peso ≥ 2,0, sinalizando quem ficou abaixo do mínimo
3. **Hard failures** — quando existem, com o código
4. **Motivos de revisão** — específicos, citando critério e nota
5. **Warnings** — categorizadas
6. **Avaliadores** — Judge A e B **recolhidos**, expansíveis

Um engenheiro precisa saber se pode seguir antes de precisar saber o que dois avaliadores acharam de cada critério.

## Os quatro veredictos

| Veredicto | Forma | Ação | Tratamento |
|---|---|---|---|
| `APPROVED` | círculo com check, verde | `PROCEED` | Sem celebração; verde discreto |
| `APPROVED_WITH_WARNINGS` | quadrado, âmbar | `PROCEED_WITH_WARNINGS` | Warnings sempre visíveis |
| `HUMAN_REVIEW_REQUIRED` | losango, laranja | `ENGINEERING_REVIEW` | Não é erro; é encaminhamento |
| `REJECTED` | círculo com X, vermelho | `BLOCK_RESULT` | Visualmente distinto de revisão |

`REJECTED` com nota alta é renderizado sem contradição aparente: o caso mockado mostra 3,4/4 e mesmo assim bloqueado, porque hard failure não é compensada por média.

## Claim lineage

Responde a pergunta que decide confiança: *de onde saiu essa afirmação?*

Cada claim expõe a cadeia numa linha: `claim → evidence → tool → trace event → source`, com o nó de evidência acionável, abrindo o registro completo.

Uma colisão de classe CSS com o markup antigo de claims quebrava a cadeia em várias linhas; as classes novas usam o prefixo `clineage__` para não disputar com `.lineage`.

## Fila de revisão

A regra de fila é **única**: `reviewQueue()` combina handoff da investigação com `human_review_required` e `REJECTED` do Eval. O badge do menu deriva da mesma função — antes era um literal fixo `2`, que passou a contradizer a fila quando o Eval entrou.

Atribuição e "Take review" permanecem desabilitados, com aviso explícito, porque não existe workflow de posse no backend. Nenhuma integração foi inventada.

## Estratégia de mocks

Seis casos completos, cobrindo os cinco cenários exigidos:

| Caso | Terminal | Eval |
|---|---|---|
| `0418` | `GROUNDED_COMPLETION` | `APPROVED` |
| `0417` | `SAFE_ESCALATION` | `APPROVED_WITH_WARNINGS` |
| `0419` | `SAFE_ESCALATION` | `HUMAN_REVIEW_REQUIRED`, arbitragem não resolvida |
| `0416` | `GROUNDED_COMPLETION` | `HUMAN_REVIEW_REQUIRED` — demonstra a distinção |
| `0415` | `FAILED` | `REJECTED` por `REPORTER_FABRICATED_CLAIM` |
| `0420` | `AWAITING_REQUIRED_INFORMATION` | **sem avaliação** — não chegou ao Eval |

A ausência de avaliação em `0420` é intencional e renderizada com explicação, não como erro.

O array `additionalRows` de linhas-resumo foi removido: com todos os casos completos, ele só produzia um tipo `never[]` e impedia abrir metade da lista.

## Fronteira com o backend

Não há API HTTP conectando os dois. Os mocks são tipados contra os contratos reais e ficam marcados como `MOCK DATA` na interface e `mock: true` no dado.

Quando a API existir, a substituição é trocar `mock-investigations.ts` e `mock-evaluations.ts` por um cliente — os componentes não mudam, porque consomem os tipos e não os mocks.

## Verificação visual

Playwright em 1440, 1280 e 1024px, com captura de dez telas por largura. Zero overflow horizontal e zero erro de console nas três.

Defeitos encontrados e corrigidos na inspeção, não no build: cabeçalhos da fila de revisão desalinhados do conteúdo, pill de qualidade esticando na célula, colisão de classe no lineage, e o badge fixo do menu.

## Limitações conhecidas

1. Dados mockados; sem integração viva.
2. Página única com views internas, não rotas — o deep-link por URL não existe.
3. Atribuição de revisor não implementada, por ausência de backend.
4. Mobile não é prioridade; abaixo de 1024px o layout degrada mas não quebra.
5. `GOLDEN_ALIGNMENT` não aparece na UI porque nenhuma run real foi avaliada com referência.
