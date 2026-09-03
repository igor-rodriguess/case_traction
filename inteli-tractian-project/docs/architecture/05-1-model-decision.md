# Etapa 05.1 — Decisão do modelo do Understanding Agent

Data da decisão técnica: 2026-09-02

Status: **READY_FOR_MODEL_APPROVAL**

Esta etapa recomenda um modelo e congela uma configuração experimental. Ela não autoriza nem executa inferência. Foram realizadas zero chamadas externas, zero execuções DEV e zero consumo de tokens.

## Decisão recomendada

```text
SELECTED_PROVIDER=openai
SELECTED_MODEL=gpt-4.1-mini-2025-04-14
MODEL_BASE=gpt-4.1-mini-2025-04-14
```

A escolha usa o snapshot, e não o alias móvel, para reduzir mudanças de comportamento durante o experimento. O modelo é uma versão menor e de baixa latência da família GPT-4.1, suporta Structured Outputs, possui snapshot fixo e aceita supervised fine-tuning na mesma base. Isso preserva a comparação futura entre baseline prompt-only e fine-tuned sem escolher o modelo de maior porte por conveniência.

A documentação oficial consultada informa preços de USD 0,40 por milhão de tokens de entrada e USD 1,60 por milhão de tokens de saída. O preço e a disponibilidade devem ser verificados novamente imediatamente antes do smoke test.

## Disponibilidade no projeto

O projeto ainda não possui SDK de LLM ou adapter concreto instalado. Existe apenas a interface `StructuredModelProvider`; o `UnderstandingAgent` não conhece qualquer SDK. O Makefile já prevê `OPENAI_API_KEY`, `BASE_URL` e `MODEL`, tornando OpenAI-compatible a única direção antecipada pelo material local.

A implementação futura deverá preservar:

```text
UnderstandingAgent
        ↓
StructuredModelProvider
        ↓
OpenAIStructuredModelAdapter
        ↓
OpenAI Responses API
```

O pacote Python `openai` e sua versão deverão ser adicionados e congelados apenas na etapa de implementação do adapter. Nenhuma dependência foi instalada nesta decisão.

## Shortlist

| Provider | Modelo exato | Structured Output | Fine-tuning comparável | Preço input/output por 1M | Decisão |
|---|---|---|---|---:|---|
| OpenAI | `gpt-4.1-mini-2025-04-14` | Sim, JSON Schema estrito | Sim, SFT na mesma base | USD 0,40 / 1,60 | Recomendado, pendente de aprovação |
| OpenAI | `gpt-4o-mini-2024-07-18` | Sim | Sim | USD 0,15 / 0,60 | Viável e mais barato, mas geração anterior |
| OpenAI | `gpt-4.1-nano-2025-04-14` | Sim | Sim | USD 0,10 / 0,40 | Rejeitado: documentação atual marca o snapshot como deprecated |

Modelos Anthropic foram excluídos da shortlist porque o repositório não possui adapter, configuração ou credencial prevista para esse provedor, e não foi comprovado um caminho de SFT comparável para o projeto. Modelos locais também ficaram fora: não existe runtime, base baixada nem capacidade de hardware registrada. GPT-5 Mini não foi selecionado porque não foi confirmado um caminho de SFT na mesma base nas fontes oficiais revisadas. Essas opções exigiriam nova decisão arquitetural, não uma troca silenciosa.

## Structured Output

O adapter deverá usar a Responses API com `text.format` do tipo `json_schema` e `strict=true`, alimentado por `UnderstandingOutput.model_json_schema()`. A resposta continua sujeita à validação local de `UnderstandingOutput`; schema inválido é resultado experimental, não algo a ser reparado ou ocultado.

Não serão oferecidas tools ao modelo. O Understanding Agent permanece interpretativo, sem `TractianClient`, Investigator ou Evidence Ledger.

## Configuração congelada proposta

| Campo | Valor |
|---|---|
| model | `gpt-4.1-mini-2025-04-14` |
| prompt_version | `understanding_prompt_v1` |
| temperature | `0.0` |
| top_p | não enviar |
| max_output_tokens | `2048` |
| timeout total | `30s` |
| seed | `NOT_SUPPORTED` na Responses API revisada |
| concurrency | `1` |
| store | `false` |
| truncation | `disabled` |
| structured output | JSON Schema estrito |

Temperatura zero e snapshot fixo reduzem variabilidade, mas não prometem determinismo matemático. Cada resultado deverá preservar o identificador retornado pelo provedor, configuração, timestamps, latência, tokens e tentativas.

## Retry

Falhas de transporte e falhas do modelo são tratadas separadamente.

São permitidas no máximo três tentativas totais para conexão, timeout, HTTP 429 e HTTP 5xx. Deve-se respeitar `Retry-After`; na ausência dele, usar espera exponencial de 1 e 2 segundos com jitter limitado. Todas as tentativas entram no log.

Não há retry para HTTP 400, 401 ou 403, recusa, JSON inválido, quebra de schema, erro semântico ou saída interrompida por limite. Esses resultados permanecem nas métricas. Em especial, não se repete uma resposta ruim para melhorar artificialmente o baseline.

## Credencial

A única variável secreta esperada é:

```text
OPENAI_API_KEY
```

Ela não poderá entrar em código, Git, dataset, Trace, invocation log, erros, predictions ou showcase. O `.gitignore` foi reforçado com `.env`, `.env.*` e a exceção `!.env.example`. Um eventual `.env.example` deve conter apenas nomes e valores fictícios. Cabeçalhos de autorização devem ser redigidos antes de qualquer log.

## Retenção e privacidade

Serão enviados somente mensagem e contexto sintéticos do DEV, prompt versionado e JSON Schema. Dados sintéticos reduzem o risco, mas não eliminam governança.

Segundo a política oficial revisada, dados da API não são usados para treinar modelos do provedor, salvo opt-in explícito. Por padrão, conteúdo pode permanecer por até 30 dias em logs de monitoramento de abuso. O adapter deverá usar `store=false` e não deverá criar conversations, files, batches ou outro estado hospedado.

Zero Data Retention depende de elegibilidade e aprovação separada do provedor; portanto, não foi assumido. Antes do smoke test, o responsável precisa aceitar explicitamente a retenção padrão ou comprovar que o projeto possui ZDR habilitado.

## Estimativa de custo

A medição local — sem chamar modelo — encontrou 10.031–10.136 caracteres de entrada por amostra, incluindo prompt, user input e schema, e targets esperados de 760–1.250 caracteres. Usando uma faixa conservadora de 3–4 caracteres por token:

| Execução | Estimativa |
|---|---:|
| Smoke test, 5 amostras | USD 0,00652–0,01016 |
| Baseline, 60 amostras | USD 0,07824–0,12192 |
| Repetição completa | USD 0,07824–0,12192 adicionais |
| Teto conservador de 60, se toda saída atingir 2.048 tokens | USD 0,27821 |

Uso real reportado pelo provedor é a fonte de verdade. Prompt caching ou descontos não entram na previsão.

Proposta de hard caps, ainda **PENDING_APPROVAL**:

- smoke test: USD 0,05;
- baseline completo: USD 0,50;
- repetição completa: USD 0,50;
- proposta cumulativa: USD 1,05.

Antes de cada request, o runner futuro deve somar custo registrado e projeção conservadora da próxima chamada. Se ultrapassar o cap da fase, deve parar antes da chamada e registrar `BUDGET_EXCEEDED`.

## Escopo experimental congelado

Somente o split sintético `dev` poderá ser autorizado. Nesta decisão, `dev_execution_authorized=false`: o escopo está definido, mas chamadas ainda dependem de aprovação.

Continuam bloqueados:

- `train`;
- `holdout`;
- Golden Set;
- ACTION tools;
- Investigator;
- LangGraph;
- fine-tuning.

O adapter receberá um `UnderstandingInput`; ele não terá loader nem caminho para qualquer split.

## Smoke test obrigatório

Após as aprovações e a implementação testada do adapter, executar separadamente estas cinco amostras DEV:

| Sample | Cobertura |
|---|---|
| `syn_u_dev_0001` | contextualize |
| `syn_u_dev_0011` | investigate |
| `syn_u_dev_0036` | pedido de execução sem executar ACTION |
| `syn_u_dev_0049` | mixed |
| `syn_u_dev_0050` | unclear |

O smoke valida credencial, adapter, schema, serialização, tracing, uso de tokens, erros e custo. Ele não autoriza ajuste informal do prompt. Mudança motivada por comportamento do modelo exige nova `prompt_version` e novo registro experimental; correções puramente infraestruturais devem ser identificadas como tal.

## Baseline completo futuro

Depois de um smoke tecnicamente válido, uma autorização separada poderá liberar exatamente as 60 amostras DEV, com o mesmo snapshot, `understanding_prompt_v1` e configuração congelada. Todas as predictions e falhas serão preservadas, sem seleção de casos favoráveis. O baseline completo não foi executado nesta etapa.

## Comparabilidade com fine-tuning

A documentação oficial lista `gpt-4.1-mini-2025-04-14` para supervised fine-tuning. Um experimento futuro deverá partir desse mesmo snapshot e comparar contra os artefatos congelados do baseline. Isso não autoriza treino, acesso ao train, holdout ou Golden Set nesta fase.

## Aprovações humanas restantes

1. Aprovar OpenAI e `gpt-4.1-mini-2025-04-14`.
2. Autorizar o uso de `OPENAI_API_KEY` e confirmar acesso/billing do projeto.
3. Aceitar retenção padrão ou comprovar ZDR.
4. Aprovar cap de USD 0,05 para o smoke.
5. Aprovar cap de USD 0,50 para o baseline, separadamente.
6. Autorizar implementação e pinagem do SDK/adapter.
7. Rever preço e disponibilidade imediatamente antes do smoke.
8. Autorizar explicitamente as cinco chamadas do smoke.

Até essas decisões, o estado não é `READY_FOR_SMOKE_TEST`.

## Fontes oficiais verificadas

- [GPT-4.1 Mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
- [GPT-4o Mini](https://developers.openai.com/api/docs/models/gpt-4o-mini)
- [GPT-4.1 nano](https://developers.openai.com/api/docs/models/gpt-4.1-nano)
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Supervised fine-tuning](https://developers.openai.com/api/docs/guides/supervised-fine-tuning)
- [Controles e retenção de dados](https://developers.openai.com/api/docs/guides/your-data)
- [Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)

**Final status: READY_FOR_MODEL_APPROVAL**
