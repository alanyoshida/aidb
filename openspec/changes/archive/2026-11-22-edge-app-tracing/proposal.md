# Proposal

## Why

O portal (v1.8.0) e o chart (v1.9.0) já levam traços ao APM. As apps geradas, porém, só aparecem como pedidos `GET` do serviço `traefik`, todos misturados. Hoje não dá para ver, por app, quantos pedidos ela recebe, quanto demora ou quantos erros devolve.

O Traefik já está no caminho de todo pedido a `/apps/<slug>`. Rastrear a borda dá essa visão sem instrumentar o código gerado.

Esta é a terceira e última change de observabilidade (portal, chart, borda). Ela fecha o desenho em que cada sistema aparece como um serviço só, com os traços da borda e as métricas de CPU e memória do `kubeletstats` sob o mesmo nome.

## What Changes

- **Cada app vira um serviço no APM.** O Collector tira o slug do caminho original do pedido (`/apps/<slug>/...`) e define `service.name` igual ao slug no span de servidor do Traefik. Isso vale nos três caminhos de rota (Docker, `ingressroute` e `gateway`), porque não depende do nome do router. Latência, vazão e taxa de erro por app vêm das métricas que o APM Server deriva desses spans.
- **Nome de transação útil e sem identificadores.** O pedido `GET /apps/crm/clientes/42` vira a transação `GET /clientes/{id}` no serviço `crm`. O prefixo da app sai, e segmentos numéricos ou com cara de identificador viram `{id}`. Isso evita uma transação por registro.
- **Assets e websocket do NiceGUI fora da borda**, tanto do portal quanto das apps. Hoje cada arquivo estático vira uma transação do Traefik.
- **Query string removida no Collector** também, para os spans do Traefik. O Traefik 3.7 do chart já mascara os valores, mas o 3.1 do compose não garante isso.
- **Traefik do compose com tracing opcional.** Um segundo arquivo de configuração estática, com tracing OTLP para `otel-collector`, é escolhido por uma variável. O padrão continua sem tracing, para o Traefik não tentar exportar quando não há Collector.
- **Os mesmos processadores nos três Collectors** (perfil Elastic, perfil Grafana e chart), conferidos por teste.
- **Docs:**
  - ADR 0035;
  - `docs/operacao.md`, com como ligar a borda no compose;
  - README do chart.
- **Fora do escopo:**
  - instrumentação dentro das apps: o `traceparent` já chega a elas, então uma app instrumentada no futuro entra no mesmo traço;
  - métricas OTLP do Traefik por app;
  - o compose de produção;
  - remover o IP e o user agent dos spans (questão em aberto).

## Capabilities

### New Capabilities

(nenhuma)

### Modified Capabilities

- `service-observability`: requisitos novos para a borda das apps:
  - serviço por app;
  - nome de transação normalizado;
  - assets e websocket fora;
  - query string removida no Collector;
  - tracing opcional do Traefik no compose.

  Nenhum requisito atual muda.

## Impact

- **Collectors:**
  - `deploy/observability/otel-collector-elastic.yaml` e `otel-collector-tempo.yaml`;
  - a configuração gerada pelo chart (`templates/_otel.tpl`).
- **Compose:** `deploy/traefik/traefik-otel.yml`, novo; `deploy/docker-compose.yml`, com a variável que escolhe o arquivo estático e monta os dois.
- **Testes:**
  - teste unitário que compara os processadores da borda nos três Collectors;
  - verificação com spans sintéticos num Collector local, cobrindo os formatos de caminho dos três modos de rota.
- **Código do portal e chart:** nenhuma mudança no portal. A única mudança no chart é a configuração gerada do Collector.
- **Verificação ao vivo:** no compose, com uma app gerada pelo harness fake, mandando para o Elastic de teste.
