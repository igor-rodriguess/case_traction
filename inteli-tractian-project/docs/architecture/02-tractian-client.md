# TractianClient

## 1. Responsabilidade

`TractianClient` é a única camada de comunicação HTTP da aplicação com a API industrial TRACTIAN. Ele centraliza base URL, conexão `httpx`, timeout, headers, execução, parsing e normalização de respostas e erros. Não contém decisões de agente ou interpretação diagnóstica.

Localização: `api/app/integrations/tractian_client.py`. A pasta `integrations` mantém o limite HTTP dentro do pacote `app` sem misturá-lo aos handlers FastAPI fornecidos.

## 2. Posição na arquitetura

```text
futuras tools → TractianClient → API TRACTIAN
```

As futuras tools não precisarão construir URLs, headers ou interpretar diretamente envelopes HTTP. Nenhuma tool ou agente foi criado nesta etapa.

## 3. RequestContext

`RequestContext` é imutável e contém somente `user_id: str | None`, o único valor confiável atualmente exigido pela API para identidade. Quando presente, o client deriva dele o header `x-user-id`.

Nenhum dos 18 métodos de endpoint aceita `user_id`, `x_user_id` ou `headers`. `company_id` e `case_id` não foram adicionados ao contexto porque o runtime atual os trata como IDs de recursos, não como identidade ou autorização confiável. A ausência de isolamento por empresa permanece uma limitação da API.

## 4. Transport status vs evidence status

`ClientResult` preserva separadamente:

- transporte: `transport_ok`, `status_code`, método e path;
- evidência: `evidence_status`, restrito a `complete`, `partial`, `inconclusive`, `conflict` e `unavailable`;
- conteúdo: `data` e `notes`;
- rastreabilidade: nome e natureza da operação;
- falha: `ClientError` tipado.

Assim, HTTP 200 com `evidence_status=unavailable` continua sendo transporte bem-sucedido e evidência indisponível. `/users/me` e ACTIONs não usam envelope probabilístico e retornam `evidence_status=None`.

## 5. READ vs ACTION

O registro imutável `TractianClient.OPERATIONS` mapeia as 18 operações confirmadas no runtime:

- 13 READ;
- 5 ACTION.

Cada `ClientResult` inclui `operation_kind`. O client não cria Human Gate nem bloqueia ACTIONs por política adicional. Respostas ACTION preservam apenas o acknowledgement retornado (`accepted`, `action_id`, `message`); não afirmam persistência.

## 6. Tratamento de erros

Erros normalizados:

- `timeout` para `httpx.TimeoutException`;
- `connection` para falhas de transporte `httpx.RequestError`;
- `http_status` para respostas não-2xx, preservando payload, código e mensagem;
- `invalid_json` quando a resposta não pode ser parseada;
- `invalid_response` quando um READ envelopado não contém um dos cinco estados conhecidos.

`unavailable` em HTTP 200 não é convertido em erro de conexão. Não há retry automático: os modos sintéticos são determinísticos por recurso/seed e as ACTIONs não têm idempotência comprovada.

## 7. Limitações conhecidas

- O header `x-user-id` não é autenticação criptográfica; o client apenas impede que camadas futuras o forneçam por método.
- A API não aplica escopo de empresa/tenant.
- ACTIONs podem retornar aceite sem persistir mudança ou expor status posterior.
- Schemas runtime são genéricos; `data` permanece tipado como `Any` até contratos de payload serem estabilizados.
- Dependências não possuem lock file.
- O client é síncrono, coerente com a API e os testes atuais.

## 8. Decisões adiadas

- Human Gate, confirmação e política de autorização;
- idempotência, retry e backoff;
- Evidence Ledger, trace e telemetria;
- modelos tipados específicos para cada payload;
- client assíncrono;
- autenticação real e isolamento por tenant;
- tools, agentes, prompts e LangGraph.

## 9. Resultados dos testes

Os testes do client usam `httpx.MockTransport` e não dependem de servidor externo, LLM ou dados de avaliação.

| Suíte | Casos | Resultado |
|---|---:|---:|
| API original | 39 | 39 passed |
| TractianClient | 17 | 17 passed |
| Total | 56 | 56 passed |

Resultado final: 56 passed, 0 failed, 0 skipped, 1 warning em 4,28 s. O warning preexistente é `StarletteDeprecationWarning` sobre a integração TestClient/httpx. Nenhum código novo importa ou lê `eval/expected-paths.json` ou outro ground truth de avaliação.
