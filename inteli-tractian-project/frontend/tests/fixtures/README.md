# Fixtures

Estes arquivos foram a fonte de runtime até a Etapa 12. Agora servem apenas como
fixture: a aplicação lê exclusivamente da API (`lib/api.ts`).

Nenhum código em `app/`, `components/` ou `lib/` os importa. Não existe fallback
"API falhou → usa mock": esconder a falha seria pior que mostrá-la.
