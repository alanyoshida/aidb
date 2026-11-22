# Design

## Context

- **Spans do Traefik 3.7 (chart), vistos no Elastic de teste na verificação da v1.9.0.** Cada pedido gera dois spans:
  - o de servidor, chamado só `GET`/`POST`, com `url.path`, `url.full`, `http.request.method`, status, IP do cliente e user agent. `url.query` sai com os valores trocados por `REDACTED`;
  - um filho `ReverseProxy` (cliente), com o endereço do upstream em `url.original`. Esse endereço já vem sem o prefixo `/apps/<slug>`, porque a rota tira o prefixo antes de repassar, e no Kubernetes é o IP do Pod.
- **Nenhum span traz o nome do router.** E os nomes variam por modo: `app-<slug>` no Docker, `<ns>-appaiforge-sys-<slug>-…@kubernetescrd` no `ingressroute`, e outro no `gateway`. O que é igual em todos é o caminho original `/apps/<slug>/...` no span de servidor.
- **Assets na borda.** Os assets do NiceGUI (`/_nicegui/...`) e o websocket (`/_nicegui_ws/...`), do portal e das apps (que também são NiceGUI, ADR 0010), geram spans na borda. O portal os exclui da própria instrumentação, mas o Traefik não.
- **Compose.** Usa o Traefik 3.1 com configuração estática em arquivo (`--configFile=/etc/traefik/traefik.yml`). O Traefik não mistura fontes de configuração estática (arquivo, CLI, variáveis de ambiente), então não dá para ligar o tracing por um argumento extra.
- **Três Collectors** já existem com pipelines de traços: o do perfil Elastic, o do perfil Grafana e o gerado pelo chart (`templates/_otel.tpl`).
- **`kubeletstats`** (v1.9.0) já põe `service.name` igual ao slug nas métricas dos Pods de sistema.

## Goals / Non-Goals

**Goals:**
- um serviço por app no APM, com transações de nome estável e sem identificadores;
- o mesmo resultado nos três modos de rota e nos dois backends de exemplo;
- nenhum dado de query string nos spans da borda;
- assets e websocket fora.

**Non-Goals:**
- spans de dentro das apps;
- métricas OTLP do Traefik por app (o APM Server já deriva latência, vazão e erro dos spans);
- o compose de produção;
- mudar o nome ou o serviço do filho `ReverseProxy`.

## Decisions

### D1. Slug tirado do caminho, no span de servidor, só no Collector

Num processor `transform/edge` (contexto `span`), só para spans do recurso com `service.name == "traefik"` e com `url.path` casando `^/apps/[a-z0-9-]+`:
- copiar `url.path` para `appaiforge.slug` e reduzir com `replace_pattern` a `^/apps/([a-z0-9-]+).*$` → `$$1`;
- calcular o nome da transação (D2).

Por que o caminho, e não o router: o caminho é igual nos três modos, e o router não chega nos spans. O mesmo princípio do ADR 0026 (rotular na coleta, não na plataforma) aplicado à borda.

Alternativa descartada: `ExtractPatterns(...)["slug"]`. Indexar o resultado de uma função do OTTL não é garantido na 0.112; `replace_pattern` sobre uma cópia é.

### D2. Nome da transação: método e caminho dentro da app, com `{id}`

Com uma cópia de `url.path`:
1. tirar `^/apps/[a-z0-9-]+`, e usar `/` se sobrar vazio;
2. trocar segmentos só com dígitos (`/[0-9]+(/|$)` → `/{id}$$1`) e segmentos hexadecimais ou UUID com 16 caracteres ou mais (`/[0-9a-fA-F-]{16,}(/|$)` → `/{id}$$1`);
3. `name = Concat([attributes["http.request.method"], <caminho>], " ")`.

A cópia temporária é apagada no fim.

Limitação aceita: dois identificadores seguidos (`/1/2`) só têm o primeiro trocado, porque as ocorrências não se sobrepõem.

Alternativa descartada: manter `GET`. Todas as transações de uma app ficariam com o mesmo nome.

Alternativa descartada: o caminho cru. Uma transação por registro estouraria a cardinalidade no APM.

### D3. Serviço por app com `groupbyattrs`

O recurso (`service.name=traefik`) é um só para todos os spans de um lote. Para cada app virar um serviço, o processor `groupbyattrs/edge` (chave `appaiforge.slug`) move os spans com slug para recursos próprios, copiando os atributos do recurso. Em seguida, `transform/edge-service` (contexto `resource`) define `service.name = attributes["appaiforge.slug"]` onde houver slug.

**Consequência:** o filho `ReverseProxy` não tem o caminho original, então continua no serviço `traefik`. No APM, ele aparece como span do Traefik dentro da transação da app.

**Alternativa descartada:** agrupar pelo traço (`groupbytrace`) para levar o filho junto. O OTTL não lê atributos de outro span, e o `groupbytrace` segura os traços em memória.

### D4. Filtro de assets e websocket

O processor `filter/edge` descarta, no recurso `traefik`, os spans cujo `url.path`, `url.full` ou `url.original` contém `/_nicegui`. O `ReverseProxy` manda o upstream em `url.full` (o APM Server o mostra como `url.original`); o primeiro desenho só olhava `url.original`, e a verificação ao vivo pegou o websocket do portal passando. Isso cobre `_nicegui_ws`, e cobre o filho `ReverseProxy`, cujo `url.original` traz o caminho do upstream. As condições checam `!= nil` antes de `IsMatch`. A filtragem é feita antes do `transform/edge`, para não calcular nome de span descartado.

### D5. Query string removida no Collector

No mesmo `transform/edge`, para todo span do recurso `traefik`:
- `delete_key(attributes, "url.query")`;
- `replace_pattern` de `\?.*$` → vazio em `url.full`, `url.original`, `http.target` e `http.url`.

É defesa em profundidade: o Traefik 3.7 do chart já mascara os valores, mas o 3.1 do compose não garante.

### D6. O mesmo bloco nos três Collectors, conferido por teste

Os processors `filter/edge`, `transform/edge`, `groupbyattrs/edge` e `transform/edge-service` são escritos iguais em:
- `otel-collector-elastic.yaml`;
- `otel-collector-tempo.yaml`;
- `collectorConfig` do chart.

Ficam no pipeline de traços, depois do `memory_limiter` e antes do `batch`. Um teste unitário carrega os dois arquivos do compose e o render do chart e compara esses quatro processors.

A configuração própria do operador no chart (`collector.config`) não recebe nada: quem a fornece decide.

Alternativa descartada: um arquivo comum incluído pelos três. O Collector não tem `include` de trecho de configuração, e o chart renderiza a dele.

### D7. Traefik do compose: segundo arquivo estático escolhido por variável

- `deploy/traefik/traefik-otel.yml` = `traefik.yml` + `tracing.otlp.http.endpoint: http://otel-collector:4318/v1/traces`.
- O serviço `traefik` passa a montar a pasta `deploy/traefik/` e usar `--configFile=/etc/traefik/${APPAIFORGE_TRAEFIK_CONFIG:-traefik.yml}`.

O padrão não muda. Ligar é `APPAIFORGE_TRAEFIK_CONFIG=traefik-otel.yml`, com um perfil de observabilidade de pé.

Alternativa descartada: tracing sempre ligado no `traefik.yml`. O Traefik tentaria exportar sem Collector, enchendo o log.

Alternativa descartada: argumentos de linha de comando. O Traefik não aceita misturar CLI com o arquivo.

### D7b. Traefik do compose de desenvolvimento na 3.7.17 (decidido na verificação)

Achado ao vivo: o Traefik 3.1 gera um span para cada peça do caminho (`EntryPoint`, `Router`, `Service`, `ForwardAuth`, `StripPrefix`, `ReverseProxy`), e esses spans intermediários não têm caminho. Quando o `filter/edge` descarta o span de servidor de um asset ou do websocket, eles ficavam órfãos no serviço `traefik`.

O 3.7 do chart gera só o span de servidor, o `AuthRequest` do `forwardAuth` e o `ReverseProxy`. Também mascara a query string sozinho.

O operador escolheu subir o `docker-compose.yml` de desenvolvimento para a 3.7.17, a mesma versão do subchart. O compose de produção e os de e2e continuam na 3.1. A configuração dinâmica é compatível: verificado que o portal, o `forwardAuth` e a app continuam funcionando.

Alternativa descartada: descartar os spans intermediários no Collector. O `ReverseProxy` ficaria sem pai e a cascata das apps quebraria.

### D8. Verificação com spans sintéticos num Collector local

Um teste de integração sobe o Collector 0.112.0 (Docker) com o bloco da borda, um receiver OTLP e um exporter de arquivo. Ele manda spans sintéticos com os caminhos que o Traefik vê, e confere a saída:
- `/apps/crm/clientes/42?cpf=...` → serviço `crm`, nome `GET /clientes/{id}`, sem query;
- `/apps/crm/` → `GET /`;
- `/apps/crm/_nicegui/...` → nada;
- `/login` → continua `traefik`;
- `ReverseProxy` com `url.original` de asset → nada.

Isso prova o tratamento independente de modo de rota. A verificação ao vivo fica com o compose e uma app de verdade.

## Risks / Trade-offs

- **[`ReverseProxy` em outro serviço]:** verificado ao vivo: a cascata fica `transação da app → AuthRequest (traefik) → transação do portal` e `→ ReverseProxy (traefik)`, coerente. O plano B não foi necessário. Risco original: a transação fica no serviço da app, e o filho no `traefik`. → Verificar ao vivo como o Kibana mostra a cascata. Se a transação da app ficar sem o filho ou quebrada, descartar o `ReverseProxy` dos pedidos de app no Collector (o upstream do Docker traz `appaiforge-sys-<slug>` no host) e registrar.
- **[Slug com formato fora de `[a-z0-9-]+`]:** os slugs são kebab-case validados pelo portal. Um caminho que não case fica no `traefik`.
- **[Escape `$$` na configuração do Collector]:** `$$1` vira `$1` na expansão do Collector. → O teste com spans sintéticos (D8) prova a troca.
- **[Custo do `groupbyattrs`]:** ele copia o recurso por slug em cada lote, o que é desprezível com dezenas de apps.

## Migration Plan

1. Compose: nada muda sem `APPAIFORGE_TRAEFIK_CONFIG`. Para ligar, suba um perfil de observabilidade e recrie o `traefik` com a variável.
2. Chart: a configuração gerada do Collector ganha os processors. O `checksum/config` reinicia o Collector no `helm upgrade`. O tracing do Traefik continua sendo ligado pelos valores da v1.9.0.
3. Rollback: voltar a versão do chart ou a variável. Os dados já exportados ficam como estão.

## Open Questions

- **IP e user agent.** Os spans de servidor (do Traefik e do portal) levam o IP do cliente e o user agent. Removê-los, ou anonimizar o IP, é uma decisão de privacidade que vale para toda a observabilidade, não só para a borda. Fica para uma change própria, se o operador quiser.
