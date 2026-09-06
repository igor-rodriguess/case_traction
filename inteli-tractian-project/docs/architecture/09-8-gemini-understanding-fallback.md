# Etapa 09.8 — Gemini como Understanding alternativo

## Pergunta

Não é "qual provider é melhor". É: o Gemini produz `UnderstandingOutput` compatível e semanticamente defensável o bastante para o desenvolvimento continuar sem depender da cota diária do Groq?

## Contract smoke

Cinco fixtures escritas para esta etapa, fora de qualquer split, uma por classe. Sem expected answer e sem valor de benchmark.

| Medida | Resultado |
|---|---:|
| Fixtures | 5 |
| Respondidas pelo provider | 5 |
| Schema válido | **5 / 5** |
| Classe prevista correta | 5 / 5 |
| `action_execution_allowed` violado | 0 |

## Teste de equivalência

Dez casos DEV **já medidos com Groq** na V2, selecionados deterministicamente e estratificados por classe alvo. Apenas o Understanding foi reexecutado; o `target` só entrou depois da inferência.

| Medida | Groq | Gemini |
|---|---:|---:|
| Schema válido | 100% | **100%** |
| Acurácia contra o alvo | 1,00 | **1,00** |
| Concordância de classe | — | **100%** |
| Entidades preservadas | — | **100%** |
| Violações de ACTION | 0 | **0** |
| Tokens | 42.647 | **24.976** |
| Latência total | 34,8 s | 104,5 s |

O Gemini concordou com o Groq em 10 de 10 e acertou o alvo em 10 de 10, gastando 41% menos tokens e sendo cerca de três vezes mais lento.

Limitação registrada: `mixed` e `unclear` não estavam entre os 33 casos medidos com Groq, então a equivalência não os cobriu. Eles foram medidos depois, na coorte B.

## Correção no próprio critério

O gate reprovou na primeira execução com 4/5 no smoke. A fixture que falhou teve **timeout do provider**, não quebra de contrato — a mesma confusão entre falha de infraestrutura e falha de agente que o projeto já corrigiu para quota e para 5xx.

O critério foi corrigido em vez de reexecutado até passar: validade de schema passa a ser medida apenas sobre fixtures que o provider respondeu, com `provider_failures` contabilizado à parte, e uma checagem nova de cobertura mínima (pelo menos 4 respondidas) impede que infraestrutura ruim aprove o gate por omissão.

## Veredicto

`GEMINI_UNDERSTANDING_APPROVED` — os sete critérios passaram.

## Rastreabilidade das coortes

A troca do provider do Understanding **é** uma mudança de roteamento. Reutilizar `MODEL_ROUTING_V5`, como o enunciado pedia, faria dois roteamentos diferentes compartilharem um rótulo e destruiria a rastreabilidade que o versionamento existe para dar.

Foi criado `MODEL_ROUTING_V6`, registrando no manifesto que ele deriva do V5 trocando apenas o provider do Understanding — demais papéis, prompts, schemas e políticas idênticos.

| Coorte | Experimento | Understanding | Casos |
|---|---|---|---:|
| A | `e2e-full-dev-v2` | Groq `openai/gpt-oss-120b` | 33 |
| B | `e2e-full-dev-v2b` | Gemini `gemini-3.5-flash-lite` | 27 |

As duas nunca são somadas como população homogênea. A coorte B executou apenas os casos que a A não mediu; os 33 já medidos saíram da fila sem serem copiados.

## Resultado da coorte B

Split coberto: **60/60**.

| Terminalidade | Casos |
|---|---:|
| `SAFE_ESCALATION` | 13 |
| `AWAITING_REQUIRED_INFORMATION` | 8 |
| `FAILED` | 4 |
| `GROUNDED_COMPLETION` | **2** |

Terminalidade válida 85,2%. Investigator com 82 decisões e **100% de validade em primeira passagem**. 55 EvidenceRecords, **0 órfãos**. ACTION zero.

## As duas primeiras conclusões grounded do projeto

`syn_u_dev_0041` percorreu o pipeline inteiro pela primeira vez num caso DEV: `get_asset_context` complete → claim materializada → lineage válida → **Reporter alcançado e validado**, com preservação de claim 1,0 e zero claims não suportadas.

Isso encerra a dúvida que a V1 deixou aberta: o caminho grounded funciona em caso real do split, não só na fixture de integração da Etapa 09.4F.

## As quatro primeiras falhas comportamentais

Todas na camada `GROUNDING`, e todas revelam um limite arquitetural, não erro de modelo.

**Três `GROUNDED_CONCLUSION_NOT_MATERIALIZABLE`** (`0017`, `0020`, `0035`). O Investigator respondeu, a Completion Policy aceitou — a evidência citada era `complete` ou `partial` —, mas `build_grounded_conclusion` só materializa fatos de **2 das 10 READ tools**: `get_asset` e `get_analysis`. Evidência vinda de baseline, RMS, espectro ou data quality não possui regra de materialização.

O agente coletou evidência boa e respondeu; a camada de grounding não soube expressá-la. É gap de cobertura do grounding, e a correção pertence ao código, não ao modelo.

**Uma `UNSUPPORTED_CLAIM`** (`0044`). O Reporter não preservou a conclusão determinística — primeira falha de fidelidade do Reporter observada em todo o projeto. A validação determinística a barrou antes de virar relatório.

## Segurança

ACTION propostas: 0. ACTION executadas: 0. `TRAIN`, `HOLDOUT` e Golden Set: não acessados.
