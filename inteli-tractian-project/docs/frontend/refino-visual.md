# Frontend — refino visual e português (Etapa 11.1)

Documento complementar a `evaluation-ui.md`. Registra a transformação visual, a
tradução da interface e a curadoria de conteúdo feita sobre o frontend que já
existia. Nenhum frontend novo foi criado; nenhum backend foi tocado.

## Auditoria de conteúdo

Cada informação exibida foi confrontada com a pergunta obrigatória: *existe
evidência na arquitetura, nos contratos ou na documentação de que isso ajuda a
demonstrar o produto?*

| Elemento | Decisão | Motivo |
|---|---|---|
| Estado terminal, evidências, afirmações, conclusão, relatório, avaliação | KEEP | É o núcleo demonstrável do sistema |
| Trace | SIMPLIFY | Vira "Trajetória", com horário no vão esquerdo e frase legível; `call_id` desce para os detalhes |
| Claim lineage | SIMPLIFY | Vira "Rastreabilidade da conclusão", em linguagem de negócio |
| Barra de postura de evidências (24 h) com 5 legendas | REMOVE | Widget de dashboard genérico, sem correspondente na arquitetura |
| Filtros falsos "Date: Last 7 days" e "Human review: All" | REMOVE | Controles que não filtravam nada — marca registrada de template |
| Sidebar de 224 px | REMOVE | Principal responsável pela aparência de "app"; substituída por navegação superior |
| Cartão de saúde do sistema na visão geral | REMOVE | Provedores e latência são secundários (§27); permanecem na aba Operação |
| Números fixos da visão geral (3 ativas, 18 concluídas…) | ADD/corrigido | Passaram a ser derivados dos mocks; antes contradiziam a própria lista |
| Cabeçalho da fila de revisão | ADD | Colunas não tinham rótulo |
| Tempo total no cabeçalho do caso | ADD | Exigido por §12; existia apenas na linha de metadados |
| Resumo do barema e barema completo | ADD | Não existiam |
| Análise dos avaliadores | ADD | Não existia |

Rebaixados para "Detalhes técnicos" no painel lateral: `call_id`, `evidence_id`,
código HTTP, endpoint, argumentos, carimbo de tempo bruto, provedor e modelo.

## Português

`lib/labels.ts` é a **única** fonte de tradução. Nenhum componente escreve rótulo
inline. Os enums do backend permanecem literais no dado:

| Contrato | Interface |
|---|---|
| `GROUNDED_COMPLETION` | Conclusão fundamentada |
| `SAFE_ESCALATION` | Encaminhado para revisão |
| `AWAITING_REQUIRED_INFORMATION` | Aguardando informações |
| `APPROVED` | Aprovado |
| `APPROVED_WITH_WARNINGS` | Aprovado com ressalvas |
| `HUMAN_REVIEW_REQUIRED` | Revisão técnica necessária |
| `REJECTED` | Rejeitado |

Números seguem a convenção local: `3,9 / 4,0`, `8,4 s`, `06 set 2026`.

O conteúdo dos mocks também foi traduzido — resumos, objetivos, afirmações,
limitações, relatório e observações dos avaliadores — preservando as formas dos
contratos.

## Direção visual

Editorial e técnica, em vez de painel. O padrão de agrupamento é um bloco com
rótulo à esquerda e conteúdo à direita, separado por filete:

```
Trajetória            12:42:03  ○  Solicitação recebida
Etapas executadas               │     Solicitação técnica do cliente…
pela AI durante a               │
análise.              12:42:04  ○  Entendimento concluído
```

Decisões que sustentam a aparência:

- **Sem cartões por padrão.** Hierarquia por tipografia, filete e alinhamento.
- **Raio de borda quase ausente** (0–2 px). Botão e etiqueta são as exceções.
- **Uma navegação só**, no topo, escura, com 54 px de altura.
- **Números tabulares** em toda pontuação e duração.
- **Caixa alta apenas em rótulos de seção**, nunca em conteúdo.
- **Estado por forma além de cor**: círculo, losango, quadrado, tracejado, cheio.

## Barema

O resumo mostra os critérios de maior peso, exatamente como o backend os entrega
em `critical_score_summary` — a interface não escolhe nem reordena. Abaixo,
"Ver barema completo" abre os 11 critérios reais de `eval/barema-v1.json`, com
peso, pergunta avaliada e a nota de cada avaliador lado a lado.

`lib/barema.ts` espelha o arquivo versionado apenas para fins de explicação.
Nenhuma pontuação é recalculada no cliente.

## Análise dos avaliadores

`lib/judge-analysis.ts` agrupa campos **já persistidos** em três blocos:

| Bloco | Origem no contrato |
|---|---|
| Pontos de concordância | `strengths` dos dois avaliadores + critérios com nota igual ≥ 3 |
| Pontos de atenção | `weaknesses` dos dois + critérios com nota baixa igual |
| Divergências | `agreement.disagreements` + o `reason` que cada avaliador registrou |
| Resultado | `agreement_level`, `rationale` e `arbitration` |

Não há diálogo simulado e nenhum campo de raciocínio interno é exibido. Quando
não houve divergência, a interface diz isso explicitamente em vez de deixar a
seção vazia.

## Defeitos encontrados na inspeção do browser

Nenhum destes apareceria num build verde.

| Defeito | Causa | Correção |
|---|---|---|
| Documento inteiro em serif | `html { font-family: var(--font-inter), … }` com a variável definida só no `<body>`; um `var()` indefinido invalida a declaração inteira | Famílias literais em `--font-body` / `--font-head` |
| Borda da última coluna desalinhada na tabela de avaliações | `.cell-weak { display: block }` aplicado a um `<td>`, tirando a célula da linha | Classe `.cell-muted` para célula de tabela |
| Hierarquia plana na avaliação | "Análise dos avaliadores" com o mesmo peso de "Pontos de concordância" | `.section-title` para o primeiro nível |
| Rótulo "Avaliação" duplicado | Bloco e faixa usavam o mesmo texto | Removido da faixa |
| Critérios com 700 px de vão até a barra | Coluna de nome em `1fr` | Nome fixo em 330 px + coluna vazia ao fim |
| Fila sem cabeçalho e qualidade sem rótulo | — | Linha de cabeçalho e prefixo "Qualidade das evidências" |
| Rótulo fixo cortado pela régua do dossiê | `top: 80px` menor que a altura combinada de cabeçalho e régua | `top: 108px` no dossiê |
| "1 não avaliadas" | Concordância nominal | "sem avaliação" |
| Atividade recente afirmava ordem cronológica inexistente | Texto do subtítulo | Reescrito |

## Verificação

Quatro rodadas de revisão em 1440, 1280 e 1024 px, 18 telas por largura, 54
capturas por rodada. Zero overflow horizontal e zero erro de console em todas.

`npx tsc --noEmit`, `npx oxlint` e `npx vinext build` limpos.

## Limites preservados

Nada de banco, backend, fila ou integração viva. Atribuição de revisor continua
desabilitada com aviso explícito, porque não existe workflow de posse no
backend. `GOLDEN_ALIGNMENT` aparece na tabela do barema completo marcado como
"só pontua quando existe caso de referência", e sem nota — que é a situação real.
