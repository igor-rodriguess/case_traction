# Frontend — grade, ocupação de tela e cobertura de informação (Etapa 11.2)

Última etapa de frontend isolado antes da integração real. Complementa
`refino-visual.md`. Nenhum backend foi tocado, nenhuma dependência foi
adicionada, nenhum commit foi feito.

## Problemas visuais encontrados na auditoria

Medidos sobre as capturas da etapa anterior, em 1440 px.

| Onde | Problema | Medida |
|---|---|---|
| Dossiê | Rótulo de seção fixo numa goteira de 216 px, vazia abaixo da primeira linha | ~16 % da largura desperdiçada em toda a página |
| Trajetória | Lista de etapas ocupando ~900 px de 1360, sem nada à direita | ~460 px abandonados por seção |
| Caso sem avaliação (`0420`) | Cinco seções seguidas com 2–3 linhas cada | página com aparência de wireframe |
| Visão geral | Faixa de números no topo e vazio no restante da tela | ~250 px vazios no rodapé |
| Investigações | Tabela com 6 colunas terminando em y≈710 | ~250 px vazios |
| Operação | Tabela de 3 linhas numa página inteira | página quase vazia |
| Revisão técnica | Encaminhamento só existia dentro de um painel lateral estreito | informação principal escondida |
| Listas | "1 registros", "1 evidências completas" | concordância errada |

## Decisões de grade

Grade de 12 colunas com quatro arranjos fixos, aplicados por classe. Nenhuma
página resolve largura por conta própria.

| Arranjo | Onde |
|---|---|
| **8 + 4** | Topo do dossiê (caso à esquerda, painel de resultado fixo à direita); Operação (provedores + execução); faixa de veredicto |
| **7 + 5** | Visão geral (atividade + fila e distribuição); Conclusão (rastreabilidade + limitações e segurança); Avaliação (critérios + achados) |
| **5 + 7** | Trajetória ao lado das evidências — a lista de etapas é estreita, a tabela precisa de largura |
| **6 + 6** | Disponível; usado pelo relatório internamente |

- Largura de conteúdo: `--frame: 1360px`. Goteira lateral 40 px.
- Vão entre colunas: `--col-gap` 48 px, 36 px abaixo de 1320.
- Ritmo vertical: escala `--s1…--s8` (4, 8, 12, 16, 24, 32, 48, 64). Todo
  espaçamento de seção sai dela.
- Escala tipográfica: título de página 30 px · seção 19 px · subtítulo 16 px ·
  corpo 13–14 px · metadado 11–12,5 px.
- Abaixo de 1120 px todos os arranjos colapsam para uma coluna; o painel de
  resultado deixa de ser fixo.

## Como cada vazio foi resolvido

Nenhum com decoração. Todos com informação que já existia no contrato e não
estava sendo mostrada.

| Vazio | Resolvido com |
|---|---|
| Goteira de 216 px | Removida. Seções passaram a ser numeradas (`01`, `02`, …), o que dá ordem de leitura sem gastar largura |
| Direita da trajetória | Tabela de evidências ao lado, com destaque cruzado |
| Direita do topo do dossiê | Painel de resultado fixo: estado, veredicto, pontuação, concordância, ação, qualidade e execução |
| Rodapé da visão geral | Fila curta de revisão + distribuição dos vereditos e dos estados de evidência |
| Direita da conclusão | Limitações da investigação e postura de segurança |
| Página de operação | Segunda coluna com métricas de execução |
| Encaminhamento escondido | Faixa de largura total no dossiê, com as quatro perguntas lado a lado |
| Vão sob a tabela de evidências | Coluna direita fixa, que acompanha a leitura da trajetória |

## Auditoria de cobertura de informação

| Informação | Existe no contrato | Deve aparecer | Aparecia | Ação |
|---|---|---|---|---|
| Solicitação, ativo, empresa | sim | sim | sim | mantida |
| Classificação da solicitação | sim | sim | sim | mantida |
| **Entidades identificadas** | sim | sim | **não** | **adicionada** |
| Informação faltante | sim | sim | sim | mantida |
| **Objetivos do plano** | sim | sim | **não** | **adicionada** |
| **Capacidades planejadas × usadas** | derivável | sim | parcial | **adicionada** |
| Etapas da trajetória | sim | sim | sim | mantida |
| **Argumentos da consulta** | sim | detalhe | só JSON bruto | **promovida a campos legíveis** |
| **Duração por consulta** | sim | sim | só na etapa | **adicionada à tabela** |
| **Evidência criada por cada chamada** | sim | sim | **não** | **adicionada (chip + inspetor)** |
| Evidências: origem, estado, resumo | sim | sim | sim | mantida |
| Afirmações e proveniência | sim | sim | sim | mantida |
| **Limitações consolidadas** | espalhado | sim | espalhado | **agrupadas em bloco próprio** |
| Pontos não resolvidos | sim | sim | sim | mantida |
| Relatório técnico | sim | sim | sim | mantido |
| Decisão, pontuação, ressalvas, motivos | sim | sim | sim | mantida |
| Avaliadores, convergência, divergência, arbitragem | sim | sim | sim | mantida |
| **Encaminhamento no próprio dossiê** | sim | sim | só no painel | **adicionado** |
| **Nenhuma ação de escrita executada** | derivável do método HTTP | sim | **não** | **adicionada** |
| Condições críticas violadas | sim | sim | sim | mantida |
| `call_id`, `trace_id`, código HTTP, endpoint | sim | detalhe | painel lateral | mantidos rebaixados |
| Provedor e modelo do avaliador | sim | detalhe | detalhe do avaliador | mantidos rebaixados |

### Informação adicionada

Objetivos do plano · entidades identificadas · capacidades autorizadas com marca
de uso · duração por consulta · evidência produzida por cada chamada · inspetor
de chamada com ferramenta, argumentos, duração e resultado · limitações
consolidadas com origem · postura de segurança · faixa de encaminhamento ·
distribuição de vereditos · colunas de ativo, qualidade e revisão na lista ·
filtro de revisão humana · notas dos dois avaliadores na lista de avaliações.

### Informação removida ou rebaixada

Nada foi removido nesta etapa. Permanecem rebaixados ao painel de detalhes os
identificadores internos e os metadados de provedor.

### Nada de preenchimento

Nenhum indicador inventado, nenhum gráfico decorativo, nenhum "insight de AI".
A distribuição na visão geral conta os mocks existentes; a postura de segurança
é conferida pelo método HTTP de cada consulta registrada.

## Heurísticas

| Heurística | Como aparece |
|---|---|
| Visibilidade do estado | Painel fixo no dossiê com estado, veredicto e ação recomendada sempre visíveis |
| Correspondência com o mundo real | "Evidências", "Consulta", "Ativo", "Revisão técnica" — nunca `EvidenceRecord` ou `tool_call` na primeira hierarquia |
| Controle do usuário | Abrir evidência, inspecionar chamada, expandir avaliador, abrir barema, filtrar, voltar |
| Consistência | Cada estado tem sempre o mesmo nome, a mesma forma e a mesma posição |
| Reconhecimento | O chip liga a etapa à evidência; a coluna "Sustenta" liga a evidência à afirmação; cada avaliador traz seu foco escrito ao lado do nome |
| Prevenção de erro | `Rejeitado` usa círculo cheio vermelho e barra vermelha; `Revisão técnica necessária` usa losango laranja — forma diferente, cor diferente, texto diferente |
| Minimalismo | Ruído removido; informação acrescentada |
| Recuperação | Todo estado vazio traz **Estado** e **Impacto** |

## Chamadas de ferramenta

Toda chamada relevante fica registrada; a interface controla só o nível de
detalhe. Na trajetória: nome da consulta, tipo, duração, resumo e um chip com a
evidência produzida. Em "Inspecionar chamada": ferramenta com o identificador
técnico, argumentos campo a campo, duração, resultado semântico, evidência
criada com link, e o retorno técnico ao final. Nenhum segredo é exibido.

## Limitações

`LIMITAÇÕES DESTA INVESTIGAÇÃO` reúne, com a origem de cada item: ressalvas
declaradas nas afirmações, limitações do relatório, evidências degradadas ou
indisponíveis, e informação que faltou na solicitação. O caso `0416` é o exemplo
que importa — a API não expressa janela por turno, e isso aparece como limitação
de capacidade, não como erro do agente.

## Verificação

Três rodadas em 1440, 1280 e 1024 px. Zero overflow horizontal e zero erro de
console em todas.

Correções feitas entre as rodadas: chip de evidência duplicado nas etapas
"solicitada" e "concluída" (só a que conclui produz evidência); `<li>` com
handler de mouse sem equivalente de teclado; quebra de "420 ms" e dos
identificadores de afirmação em duas linhas; espaçamento dobrado dentro das
pilhas; menu quebrando em duas linhas a 1024 px e cobrindo o conteúdo; blocos de
limitação e segurança espremidos por uma subdivisão dentro de coluna estreita;
concordância de plural em contagens.

`tsc --noEmit`, `oxlint` e `vinext build` limpos.

## Capturas

`docs/frontend/screenshots/antes/` — estado da etapa 11.1, em 1440 px.
`docs/frontend/screenshots/depois/` — estado atual, em 1440, 1280 e 1024 px.
