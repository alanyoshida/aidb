# Tasks

## 1. Processors da borda nos Collectors

- [x] 1.1 Escrever `filter/edge`, `transform/edge`, `groupbyattrs/edge` e `transform/edge-service` (design D1 a D5) no `otel-collector-elastic.yaml` e encaixá-los no pipeline de traços, depois do `memory_limiter` (acrescentá-lo se faltar) e antes do `batch`. Verificar com `otelcol validate` da imagem 0.112.0 sem erro.
- [x] 1.2 Copiar o mesmo bloco para `otel-collector-tempo.yaml` e para `collectorConfig` em `templates/_otel.tpl` do chart (design D6). Verificar com teste unitário em `portal/tests/unit/test_helm_chart.py`: os quatro processors são iguais nos dois arquivos do compose e no render do chart com `observability.enabled`, e estão no pipeline de traços nessa ordem. Rodar `otelcol validate` nas três configurações.
- [x] 1.3 Teste de integração com spans sintéticos (design D8): `portal/tests/integration/test_edge_collector.py` sobe o Collector 0.112.0 com o bloco do compose, um receiver OTLP/HTTP e um exporter `file`, manda os spans e confere a saída:
  - serviço `crm` e nome `GET /clientes/{id}`, sem `cpf`;
  - `GET /` para a página inicial;
  - nenhum span de `/_nicegui`;
  - `/login` no serviço `traefik`;
  - `ReverseProxy` de asset descartado;
  - UUID trocado por `{id}`.

  O teste pula se não houver Docker. Verificar com `uv run pytest tests/integration/test_edge_collector.py` verde.

## 2. Traefik do compose

- [x] 2.1 Criar `deploy/traefik/traefik-otel.yml` (design D7). No `docker-compose.yml`, montar a pasta `deploy/traefik/` e usar `--configFile=/etc/traefik/${APPAIFORGE_TRAEFIK_CONFIG:-traefik.yml}`. Verificar com `docker compose config` que:
  - o padrão continua com `traefik.yml`;
  - com a variável, o comando usa `traefik-otel.yml`;
  - o Traefik sobe sem erro de configuração estática nos dois casos.

## 3. Documentação

- [x] 3.1 ADR 0035 com as decisões D1 a D7, o risco do `ReverseProxy` e a questão do IP e do user agent, mais o índice em `docs/adr/README.md`. Em `docs/operacao.md`, na seção de observabilidade, como ligar a borda no compose e como cada app aparece no Kibana. No README do chart, uma linha dizendo que os spans de `/apps/<slug>` viram um serviço por app. Verificar que o índice lista a ADR nova e que o comando documentado é o do teste 2.1.

## 4. Verificação ao vivo

- [x] 4.1 No compose (projeto próprio, como na v1.8.0), com o Collector do perfil Elastic mandando ao APM Server de teste e `APPAIFORGE_TRAEFIK_CONFIG=traefik-otel.yml`:
  - criar um sistema descartável com o harness fake e abrir a app dele;
  - acessar a app com um caminho com número e um com query string.

  Verificar no Elasticsearch de teste:
  - o serviço com o slug da app tem as transações `GET /` e `GET /<caminho>/{id}`;
  - não há spans de `/_nicegui`;
  - os valores da query string não aparecem em nenhum documento;
  - como a cascata mostra o `ReverseProxy` (design, Risks).

  Se a cascata ficar quebrada, aplicar o plano B do risco e repetir. Depois, desmontar a stack e remover o sistema e os volumes da verificação.

- Resultado da verificação (compose `aidb-otel` → APM Server de teste, já desmontado):
  - O serviço `borda-teste` tem `GET /`, `GET /busca` e `GET /clientes/{id}`, todas 200.
  - O CPF da query string não aparece em nenhum documento.
  - A cascata ficou `transação da app → AuthRequest (traefik) → transação do portal`, e `→ ReverseProxy (traefik)`.
  - Dois achados, corrigidos e registrados no design:
    - o `ReverseProxy` manda o upstream em `url.full`, e o filtro passou a olhar esse atributo;
    - o Traefik 3.1 gerava spans intermediários que ficavam órfãos, e o compose de desenvolvimento subiu para a 3.7.17 (D7b), por decisão do operador.
  - Com o 3.7.17 e o Collector corrigido, não sobrou nenhum span de `/_nicegui`.

## Workflow follow-up

- Arquivar a change (sincronizando `service-observability`) na mesma branch, antes de abrir a PR. Depois, PR, merge e release.
- Fora desta sequência: decidir sobre o IP e o user agent nos spans (questão em aberto do design).
