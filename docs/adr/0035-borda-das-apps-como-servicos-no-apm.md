# 0035 — Borda das apps: cada app como um serviço no APM, a partir dos spans do Traefik

* Status: aceito
* Data: 2026-11-22
* Decidida em: change `edge-app-tracing` (terceira e última de observabilidade: portal, chart, borda)
* Relacionada: [ADR 0025](0025-telemetria-otel-agnostica-de-backend.md) (backend só no Collector);
  [ADR 0026](0026-metricas-de-recursos-por-container-via-cadvisor.md) (rotular na coleta, não na
  plataforma); [ADR 0034](0034-observabilidade-no-chart-kubernetes.md) (`service.name` por slug
  nas métricas dos Pods)

## Contexto

O Traefik já está no caminho de todo pedido a `/apps/<slug>` e, desde a v1.9.0, manda traços OTLP
no chart. Mas os spans chegavam todos no serviço `traefik`, com nome `GET`. Não havia como ver
latência, vazão ou erro por app. Os spans do Traefik não trazem o nome do router, que de qualquer
forma muda com o modo de rota. O filho `ReverseProxy` traz o upstream já sem o prefixo da app.

## Decisão

**O slug sai do caminho original, no Collector.** No span de servidor do Traefik, um `transform`
copia `url.path` e o reduz ao slug quando casa `^/apps/[a-z0-9-]+`. O caminho é igual nos três modos
de rota (Docker, `ingressroute`, `gateway`), então o tratamento é um só.

**Cada app vira um serviço.** O recurso do Traefik é um só por lote. O `groupbyattrs` move os
spans com slug para recursos próprios, e um `transform` de recurso define `service.name` igual ao
slug. É o mesmo nome que o `kubeletstats` dá aos Pods do sistema, então, no APM, cada sistema fica
com transações e recursos juntos. O APM Server deriva latência, vazão e erro desses spans.

**Nome de transação sem identificadores.** `<método> <caminho dentro da app>`, sem o prefixo, com
segmentos numéricos e hexadecimais/UUID longos trocados por `{id}`: `GET /apps/crm/clientes/42`
vira `GET /clientes/{id}` no serviço `crm`.

**Assets, websocket e query string tratados no Collector.** Spans do Traefik com `/_nicegui` no
caminho ou no upstream (`url.full` do `ReverseProxy`) são descartados: assets e websocket do portal e das apps. A query string
sai de `url.query`, `url.full`, `url.original`, `http.target` e `http.url`, como defesa em
profundidade, porque o Traefik 3.1 do compose não garante o mascaramento que o 3.7 do chart faz.

**O mesmo bloco nos três Collectors.** Perfil Elastic, perfil Grafana e chart, conferidos por teste.
Um teste de integração manda spans sintéticos a um Collector real e confere a saída.

**Traefik do compose de desenvolvimento na 3.7.17**, a mesma versão do chart. O 3.1 gerava um span por
router, serviço e middleware, sem caminho, que ficavam órfãos quando o Collector descarta os assets.
O 3.7 gera só o span de servidor, o `AuthRequest` do `forwardAuth` e o `ReverseProxy`.

**Tracing do Traefik do compose opcional, por arquivo.** `traefik-otel.yml`, escolhido por
`APPAIFORGE_TRAEFIK_CONFIG`. O Traefik não mistura arquivo e linha de comando na configuração
estática, e o tracing sempre ligado o faria tentar exportar sem Collector.

## Alternativas consideradas

- **Rotular pelo nome do router** — descartada: não chega nos spans e muda com o modo de rota.
- **`groupbytrace` para levar o `ReverseProxy` junto** — descartada: o OTTL não lê atributos de
  outro span, e o processor seguraria os traços em memória.
- **Manter o nome `GET` ou o caminho cru** — descartada: um nome só por app não diz nada, e o
  caminho cru gera uma transação por registro.
- **Instrumentar as apps geradas** — fora desta decisão. O `traceparent` já chega a elas, e uma app
  instrumentada no futuro entra no mesmo traço.

## Consequências

- O filho `ReverseProxy` continua no serviço `traefik`, dentro da transação da app.
- Dois identificadores seguidos no caminho (`/1/2`) só têm o primeiro trocado por `{id}`.
- Um caminho cujo slug não seja kebab-case fica no serviço `traefik`.
- Os spans de servidor, do Traefik e do portal, levam o IP do cliente e o user agent. Removê-los
  ou anonimizá-los é uma decisão de privacidade em aberto, para uma change própria.
- O compose de produção e os de e2e continuam no Traefik 3.1 e sem o tracing da borda.
- Na verificação, a cascata ficou `transação da app → AuthRequest → transação do portal` e
  `→ ReverseProxy`, com o filho do Traefik no serviço `traefik`.
