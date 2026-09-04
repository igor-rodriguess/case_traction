# 09 — Real LLM Providers

## Implementação

`GroqProvider`, `GeminiProvider` e `CerebrasProvider` implementam o contrato canônico `LLMProvider` por HTTP. Payloads, respostas e diferenças de API ficam isolados nos adapters; `LLMResponse` preserva output, usage, duração, tentativas e uma categoria de erro segura. A validação Pydantic dos contratos de Planner, Investigator e Reporter permanece obrigatória depois da normalização.

Não há SDK adicional, fallback automático, execução de tool nativa ou chamada no import/startup. O registry mínimo cria o adapter a partir de `ProviderConfig` tipado.

## Configuração e segurança

`.gitignore` protege `.env`, `.env.*` e `*.env`. `api/.env` é exclusivamente local e não é rastreado; `.env.example` contém somente nomes/configurações não secretas. As chaves são lidas do ambiente no momento da inferência e nunca entram em `LLMRequest`, estado, trace, ledger, showcase ou mensagens de erro.

As seleções iniciais locais são separadas por papel:

- Understanding / Gemini: `gemini-3.5-flash-lite`;
- Planner / Gemini: `gemini-3.6-flash`;
- Investigator / Groq: `openai/gpt-oss-120b`;
- Reporter / Cerebras: `gpt-oss-120b`.

Para manter este estágio sem routing, o smoke Gemini usa somente a seleção de Understanding. Os IDs foram confirmados na documentação dos providers; isso não escolhe vencedor para benchmark.

## Structured output, retry e uso

Groq e Cerebras usam Chat Completions compatível com OpenAI e solicitam JSON Schema. Gemini solicita `responseMimeType=application/json` e `responseJsonSchema`. A confirmação do provider não substitui parse JSON e validação local de schema/contrato.

Retry é limitado a três tentativas e só cobre timeout, conexão, 429 e 5xx. Não há retry para autenticação, JSON/schema inválido, decisão/tool inválida ou ACTION. Usage só é registrado quando todos os contadores foram recebidos; billing/custo não é inferido.

## Smoke controlado executado

Em 2026-09-04 foram feitas exatamente três chamadas sintéticas, uma por provider, sem datasets, tools ou ACTIONs. Nenhuma retornou sucesso:

| Provider | Modelo | Resultado | Latência | Usage |
| --- | --- | --- | ---: | --- |
| Groq | `openai/gpt-oss-120b` | `provider_failure` | 480.878 ms | indisponível |
| Gemini | `gemini-3.5-flash-lite` | `timeout` | 15139.122 ms | indisponível |
| Cerebras | `gpt-oss-120b` | `provider_failure` | 245.759 ms | indisponível |

O resultado seguro está no showcase [09-real-provider-smoke-example.json](examples/09-real-provider-smoke-example.json). Não há nova tentativa automática: o limite da rodada foi consumido. Antes de outro smoke autorizado, é necessário diagnosticar o erro seguro que o script passará a exibir e considerar aumentar explicitamente o timeout Gemini.

## Limites e próximo passo

Não foram executados contract smoke, benchmark, routing, fallback, TRAIN/HOLDOUT/Golden Set, Eval, Judges, banco, ACTION, fila ou worker. O estágio permanece `READY_WITH_WARNINGS`: adapters e ambiente local estão prontos, mas a conectividade/saída estruturada dos três providers ainda não foi comprovada.
