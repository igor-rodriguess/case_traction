# Etapa 09.7B — Decisão de próxima fase

## Rota

**Nenhuma rota do §23 é declarada.** Com 55% do split medido, o piso `MINIMUM_SPLIT_COVERAGE = 0,80` mantém os quatro componentes em `INSUFFICIENT_EVIDENCE_TO_DECIDE`, e declarar rota contrariando o próprio guard seria fabricar conclusão.

Status: `RUN_PAUSED_PROVIDER_QUOTA`.

## O que os 33 casos já sustentam

Três coisas ficaram demonstradas no fluxo E2E, não apenas em teste isolado:

1. **A calibração do Understanding funciona.** Acurácia 0,848 → 0,970 nos mesmos casos, `execute` recall 0,00 → 1,00, zero regressões. Aberta para `mixed` e `unclear`, cujos casos não foram medidos.
2. **O reparo do teto de tokens se sustenta.** 33/33 com schema válido e `finish=STOP`, zero truncamentos, contra 4 `MAX_TOKENS` na V1.
3. **O gap temporal deixou de virar argumento inventado.** Zero argumentos rejeitados na V2, contra `time_window`, `hours` e `window` na V1. Informar o contrato da tool resolveu o que treinar o modelo não deveria resolver.

E o mais relevante para a decisão: **zero falhas comportamentais em 33 casos**, com terminalidade válida 100%.

## Leitura por componente, sem declarar veredicto

| Componente | Sinal observado | Por que não fecho |
|---|---|---|
| Understanding | 0,970 de acurácia, sem regressão | `mixed` e `unclear` não medidos |
| Planner | 100% schema, 0 truncamento | 27 casos ausentes |
| Investigator | 100% primeira passagem, 0 argumento inválido | idem |
| Reporter | não alcançado | exige conclusão grounded, que a cobertura de dados impede |

O Reporter é registrado como `REPORTER_NOT_EXERCISED_DUE_TO_DATA_COVERAGE`. A Etapa 09.4F já validou tecnicamente o caminho grounded → Reporter em fixture real.

## A regra do §24 continua valendo

Zero `GROUNDED_COMPLETION` nas duas rodadas, com **0/60 casos totalmente alinhados**. Nenhum descritor do split corresponde ao ativo que nomeia; 52 dos 60 pedem recorte temporal que nenhuma das 10 READs expressa; 10 referenciam o ativo só por anáfora.

Treinar não cria dado que a API não tem. Se a rodada fechar mantendo zero falhas comportamentais e zero grounded completion, a leitura que a evidência sustentará é `DATA_LIMITATION_BLOCKS_MODEL_EVALUATION` — o agente se comporta corretamente e o dataset não permite concluir. Mas isso só pode ser afirmado com o split medido acima do piso.

## Condição para fechar

Retomar até 60/60. Os 27 restantes precisam de ~110 mil tokens de Groq, o que exige a próxima janela diária. A retomada preserva os 33 medidos e reexecuta apenas o que a infraestrutura derrubou.

Nenhum treinamento foi executado. `TRAIN`, `HOLDOUT` e Golden Set não foram acessados.
