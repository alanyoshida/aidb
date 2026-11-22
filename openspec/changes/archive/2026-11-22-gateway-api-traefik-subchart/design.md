# Design

## Context

Motivação em `proposal.md` (Why). Estado atual que molda a abordagem:

- `KubernetesDriver.publish()` cria, por sistema, um `Service` e três objetos `traefik.io/v1alpha1`:
  `Middleware` `<nome>-auth` (`forwardAuth` para `/internal/edge/auth/<slug>`, repassando
  `X-AIDB-Identity`), `Middleware` `<nome>-strip` (`stripPrefix /apps/<slug>`) e `IngressRoute`
  (`PathPrefix(/apps/<slug>)`, prioridade 100, middlewares nessa ordem). `unpublish()` apaga os
  três. `_upsert_custom` substitui apagando e recriando.
- O chart tem `templates/ingressroute.yaml` para a rota do portal: `Host(<host>) && PathPrefix(/)`,
  prioridade 1, TLS opcional por `tlsSecretName`. Hoje a convivência com as rotas das apps depende
  só da prioridade explícita.
- O Traefik é instalado à parte (`deploy/pilot-k8s/README.md`, chart `traefik/traefik` 42.3.2,
  `traefik-values.yaml` com `hostNetwork`, só `kubernetesCRD`).
- `provisioning.reconcile()` chama `publish_app_by_slug` para todo sistema não arquivado, e a
  docstring dela diz "boot/periódico" — mas, verificado durante a implementação, **nada no portal
  a chama** (só os testes; desde o primeiro commit). Ver D6.
- O portal usa `portal.systemsNamespace` (padrão: o namespace da release) para os objetos dos
  sistemas, que pode ser diferente do namespace do portal.
- O forwardAuth precisa ver o caminho **original** (`X-Forwarded-Uri`) para devolver o usuário à
  app depois do login (`edge_auth.py`), então a autenticação tem que rodar antes da reescrita.
- Precedente de configuração inválida: `get_driver()` levanta `UnknownDriver` para um driver
  desconhecido.

## Goals / Non-Goals

**Goals:**
- Modo `gateway` com rotas das apps e do portal como `HTTPRoute` (canal standard), sem
  `IngressRoute`.
- Modo `ingressroute` idêntico ao roteamento de hoje, como padrão desta versão.
- Traefik como dependência declarada do chart, com caminho para cluster que já tem um.
- Troca de modo nos dois sentidos sem reprovisionar.

**Non-Goals:**
- Trocar o mecanismo de autenticação: o `forwardAuth` continua sendo um `Middleware` do Traefik
  nos dois modos. O filtro `ExternalAuth` da Gateway API (GEP-1494, experimental) e um sidecar de
  autenticação no Pod foram considerados na exploração e ficam para quando houver um controlador de
  destino que não seja Traefik.
- Remover o modo `ingressroute` ou mudar o padrão para `gateway`: change seguinte.
- Mudar o driver Docker (continua no file provider).
- Interceptação de rede por `iptables` no Pod e validação em cluster gerenciado real (cortes da
  etapa 8, seguem pendentes).

## Decisions

### D0. Dois modos de roteamento, transitórios, padrão `ingressroute`

`routing.mode` no chart vira `APPAIFORGE_K8S_ROUTING_MODE` no portal (`k8s_routing_mode`, padrão
`ingressroute`). O driver tem dois construtores de objetos de rota, um por modo; o resto do
`publish()` (o `Service`, o `Middleware` de auth) é comum. Um modo desconhecido faz o driver
levantar erro no `ensure_ready()`, como `UnknownDriver` faz para o driver, e o chart recusa
renderizar com valor fora de `ingressroute`/`gateway`.

O padrão `ingressroute` segue o precedente do gate de banco (`shadow` antes de `enforce`): quem
atualiza não muda de roteamento, e o modo `gateway` é ligado e observado num ambiente antes de
virar padrão. Uma change seguinte remove o modo `ingressroute`, a limpeza cruzada de D6 e o
template `ingressroute.yaml`, e passa o padrão para `gateway`.

Alternativa: corte direto para `HTTPRoute` (a versão anterior desta change) — descartada por
quebrar toda instalação Kubernetes de uma vez e só permitir voltar por `helm rollback`.

### D1. No modo `gateway`: Traefik como implementação da Gateway API, auth por `ExtensionRef`

Cada `HTTPRoute` de sistema tem uma regra `PathPrefix /apps/<slug>` com os filtros
`[ExtensionRef -> Middleware <nome>-auth, URLRewrite ReplacePrefixMatch "/"]` e `backendRefs` para o
`Service` do sistema na porta da app. O `Middleware` de strip não é usado nesse modo; o de auth é o
mesmo do modo `ingressroute`.

Alternativas: `ExternalAuth` padrão (experimental, suporte desigual entre controladores); sidecar
de auth no Pod (portável, mas muda o modelo de ameaça e quebra a paridade com o driver Docker).
Ambas descartadas agora, ver Non-Goals.

**Ordem dos filtros**: a especificação não fixa a ordem entre filtros. O spike S1 confirmou que
o Traefik 3.7.17 executa os filtros na ordem declarada (ver "Resultados dos spikes"), então a
ordem `[ExtensionRef auth, URLRewrite]` é a usada, sem recuo. O recuo que estava previsto — um
único `ExtensionRef` para um `Middleware` `chain` `[auth, stripPrefix]` — fica descartado.

### D2. No modo `gateway`: mesmo hostname nas rotas das apps quando a rota do portal tem host

A Gateway API não tem prioridade. Entre rotas, a precedência começa pelo hostname mais
específico, e só depois pelo caminho mais longo: uma rota com host explícito vence uma sem host,
mesmo com caminho menor. Por isso, quando `portalRoute.enabled`, o chart passa
`portalRoute.host` ao portal (`APPAIFORGE_K8S_ROUTE_HOSTNAME`) e, no modo `gateway`, o driver o
coloca em `spec.hostnames` de cada `HTTPRoute` de sistema. Assim as duas rotas empatam no host e
`/apps/<slug>` vence `/` pelo comprimento do caminho. Sem rota do portal, as rotas das apps saem
sem hostname (acesso por port-forward ao Traefik). No modo `ingressroute` a prioridade explícita
continua resolvendo, e o hostname não é usado.

O spike S2 mostrou que o Traefik 3.7.17 **não** aplica essa regra da especificação: mesmo com a
rota da app sem hostname e a do portal com, `/apps/<slug>` venceu (o Traefik desempata pelo
tamanho da regra). O hostname nas rotas das apps fica mesmo assim: é a forma correta pela
especificação, custa uma variável de ambiente, e protege contra o dia em que o Traefik passar a
seguir a precedência por hostname.

Alternativa: derivar o host de `auth.publicBaseUrl` — descartada porque ela pode incluir esquema e
porta e servir a outro propósito (redirect do OIDC). Configuração explícita é menos frágil.

### D3. Subchart condicional e dono do `Gateway`

`Chart.yaml` declara `traefik/traefik` (versão fixada, a mesma do piloto, 42.3.2) com
`condition: traefik.enabled`, padrão `true`. Valores repassados ao subchart, iguais nos dois modos
(os valores de um subchart não podem depender de `routing.mode`): providers `kubernetesGateway` e
`kubernetesCRD` ligados, `kubernetesIngress` desligado, e o `Gateway` padrão do subchart desligado —
o `Gateway` é do nosso chart (`templates/gateway.yaml`), para controlarmos nome, listeners e TLS.

- Modo `ingressroute`: nenhum `Gateway`; a rota do portal é o `ingressroute.yaml` de hoje
  (prioridade, entrypoints, `tls.secretName`). `traefik.enabled=false` não exige nada além disso.
- Modo `gateway` com `traefik.enabled=true`: o chart cria `Gateway` `gatewayClassName: traefik`,
  listener `web` (HTTP) e, com `portalRoute.tlsSecretName`, listener `websecure` (HTTPS,
  `certificateRefs` para o Secret, `hostname` = `portalRoute.host`). `allowedRoutes.namespaces`
  aceita o namespace da release e o dos sistemas (seletor por `kubernetes.io/metadata.name`). A rota
  do portal é `httproute-portal.yaml`.
- Modo `gateway` com `traefik.enabled=false`: nenhum controlador nem `Gateway`.
  `gateway.existing.name` e `gateway.existing.namespace` são obrigatórios (`required` no template).

O chart passa ao portal `APPAIFORGE_K8S_GATEWAY_NAME` / `_NAMESPACE` no modo `gateway` (do
`Gateway` do chart ou do existente), usados como `parentRef` das rotas dos sistemas. O `Middleware`
referenciado por `ExtensionRef` precisa estar no mesmo namespace do `HTTPRoute`, o que já é o caso:
o driver cria os dois no namespace dos sistemas.

Alternativa: pré-requisito verificado, sem subchart — escolhida a outra opção pelo operador para
ter uma instalação de um passo; o subchart desligável cobre o cluster compartilhado.

### D4. CRDs da Gateway API, instalados nos dois modos

Os CRDs da Gateway API (canal standard) precisam existir antes do `Gateway` e para o provider
`kubernetesGateway` do Traefik, que fica ligado nos dois modos. A pasta `crds/` do Helm não aceita
condição, então eles são instalados em qualquer modo — inofensivo, porque sem objetos que os usem
não fazem nada. O spike S3 mostrou que o chart do Traefik 42.3.2 **não** traz os CRDs da Gateway
API (o README dele manda aplicar o `standard-install.yaml` v1.6.3 à parte). Por isso o nosso chart
os traz em `crds/gateway-api-standard-v1.6.3.yaml`: só os CRDs do canal standard, sem a
`ValidatingAdmissionPolicy` `safe-upgrades` que o mesmo arquivo de release traz (ela não é CRD e
impõe uma política de cluster que não é nossa). O Helm só instala CRDs no `helm install` e
nunca os atualiza nem remove: o guia de operação ganha o passo manual de atualização dos CRDs ao
trocar a versão do Traefik. Achado no piloto: o mesmo vale para o `helm upgrade` de uma instalação
existente para esta versão — os CRDs da Gateway API não são instalados, e o upgrade falha em
`no matches for kind "GatewayClass"` até eles serem aplicados à mão (passo no guia e no README do
piloto).

O `GatewayClass` `traefik` vem do subchart (`gatewayClass.enabled`), que só depende do provider
`kubernetesGateway` ligado, e não do `Gateway` padrão do subchart, que fica desligado.

### D5. Substituição sem apagar e recriar, nos dois modos

Para `HTTPRoute`, `IngressRoute` e `Middleware`, o driver passa a fazer "ler → substituir com o
`resourceVersion` lido → criar se 404", em vez de apagar e recriar. A rota de um sistema que já
está no ar é republicada a cada boot (D6) e a cada novo provisionamento; apagar e recriar abriria,
em cada uma dessas vezes, uma janela em que a rota não existe (404 para quem estiver usando a app).
Vale também para o modo `ingressroute`: o roteamento observável não muda, só a janela some.

### D6. Troca de modo pela republicação das rotas no boot, com limpeza cruzada

O `publish()` de cada modo, depois de criar os seus objetos, apaga os do outro tolerando 404: no
modo `gateway`, `IngressRoute` `<nome>` e `Middleware` `<nome>-strip`; no modo `ingressroute`,
`HTTPRoute` `<nome>`. `unpublish()` apaga os objetos dos dois modos, todos tolerando 404.

O plano original contava com a reconciliação do boot para chamar `publish` em todo sistema. A
implementação mostrou que `provisioning.reconcile()` não é chamada pelo portal em execução (só
pelos testes) — lacuna anterior a esta change, que as specs `container-lifecycle` e
`container-driver-kubernetes` já descrevem como "ao iniciar e periodicamente". Verificado no
cluster de teste: trocar o modo e reiniciar o portal deixava as rotas no modo antigo.

Decisão (com o operador): o boot do portal ganha `provisioning.republish_routes()`, que, sob o
driver Kubernetes, chama `publish_app` para cada sistema **ativo** — só as rotas, sem recriar
containers nem mudar status. Uma falha num sistema é registrada e não segura os demais nem o boot.
É o que faz a troca de modo valer, nos dois sentidos, sem recriar Pods.

Alternativa descartada aqui: ligar `reconcile()` inteiro no boot. Fecharia a lacuna das duas specs,
mas muda o boot dos dois drivers (recriar containers ausentes, marcar em erro sistemas com agente
num portal de produção) — escopo próprio, fora desta change.

### D7. Chart testável sem rede

`Chart.lock` e `charts/traefik-<versão>.tgz` ficam versionados. `test_helm_chart.py` continua com
`helm template` puro, sem `helm dependency build` e sem rede.

### D8. ADR e roadmap

ADR novo (0032) registra a escolha do Traefik como implementação da Gateway API, o `ExtensionRef`
como único ponto de acoplamento, o subchart desligável e os dois modos transitórios. A "Pendência
futura — Gateway API" da etapa 8 do roadmap passa a apontar para esta change.

## Resultados dos spikes

Executados em 2026-11-22 num cluster `kind` descartável (`gwspike`, nó v1.34.0), com o chart
`traefik/traefik` 42.3.2 (Traefik v3.7.17), providers `kubernetesGateway` + `kubernetesCRD`,
CRDs da Gateway API v1.6.3 (standard), `Gateway` num namespace e as rotas em outro (seletor por
namespace), um app de eco HTTP/WebSocket e um serviço de `forwardAuth` de teste (aprova com cookie
de sessão, devolve `X-AIDB-Identity`, registra `X-Forwarded-Uri`).

- **S1 — ordem dos filtros: confirmada.** Com `[ExtensionRef auth, URLRewrite]`, o auth recebeu
  `X-Forwarded-Uri=/apps/x/relatorios?a=1` e a app recebeu `/relatorios?a=1`. Invertendo a ordem, o
  auth passou a receber `/relatorios`: o Traefik segue a ordem declarada.
- **S2 — precedência: sem risco neste Traefik.** Com as duas rotas no mesmo host, `/apps/x` chegou
  à app e `/` e `/outra/pagina` ao portal. Com a rota da app sem hostname, a app **continuou**
  vencendo; sem hostname nas duas, também. Ver D2.
- **S3 — CRDs: não vêm do subchart.** O chart 42.3.2 não traz os CRDs da Gateway API; o
  `GatewayClass` vem com `gatewayClass.enabled` mesmo com `gateway.enabled=false`. Um `IngressRoute`
  com `forwardAuth` + `stripPrefix` funcionou no mesmo Traefik, com e sem `Gateway` existente, sem
  nenhum erro no log. Ver D4.
- **S4 — WebSocket: passa.** Com sessão, o upgrade respondeu `101` e a mensagem do app chegou; sem
  sessão, `401` do auth. Uma `X-AIDB-Identity` forjada pelo cliente foi substituída pela do auth.

## Risks / Trade-offs

- [Traefik não executa os filtros na ordem declarada; a volta ao login perde o caminho original]
  → spike S1 antes de codar; recuo definido em D1 (`chain`).
- [A precedência por hostname não se comporta como esperado no Traefik e `/` captura `/apps/*`]
  → spike S2 com as duas rotas no mesmo host; teste de integração cobrindo o cenário no modo
  `gateway`.
- [WebSocket deixa de passar pelo `HTTPRoute` com `forwardAuth`] → spike S4 e o cenário de
  WebSocket na spec, testado nos dois modos.
- [Matriz de testes dobrada enquanto os dois modos existirem] → unitário e `helm template`
  parametrizados por modo; integração no kind roda nos dois. Custo aceito por ser transitório.
- [O modo `ingressroute` fica esquecido e vira permanente] → follow-up registrado em `tasks.md` e
  no ADR, com o critério para removê-lo: modo `gateway` validado no piloto.
- [Dois Traefik disputando 80/443 na atualização de um piloto com release separado, mesmo no modo
  padrão] → passo explícito no guia: desinstalar o release `traefik` antes, ou subir com
  `traefik.enabled=false` (no modo `ingressroute` não exige mais nada). A janela sem entrada é a do
  rollout do Traefik.
- [CRDs da Gateway API ficam velhos após atualizar o Traefik] → passo manual documentado (D4).
- [O portal passa a instalar componentes cluster-scoped por padrão: CRDs da Gateway API,
  `GatewayClass` e ClusterRole do Traefik] → aceito pela decisão do subchart; quem não quiser
  desliga `traefik.enabled`.
- [Subchart versionado em `.tgz` desatualiza sem ninguém notar] → versão fixada no `Chart.yaml` e
  citada no ADR; atualizar é uma change própria.

## Migration Plan

1. Instalação com Traefik em release separado: `helm uninstall traefik -n traefik` antes de
   atualizar, ou manter o release e usar `traefik.enabled=false` (no modo `gateway`, também
   habilitar o provider `kubernetesGateway` desse Traefik e informar `gateway.existing.*`).
2. `helm upgrade` do portal na versão nova, sem mudar `routing.mode`. O Traefik do subchart sobe e
   as rotas continuam no modo `ingressroute`, idênticas às de antes.
3. Para virar: `helm upgrade --set routing.mode=gateway`. O `Gateway` é criado, e o boot do portal
   republica todas as rotas pela Gateway API e apaga as do modo `ingressroute` (D6).
4. Verificação: abrir `/apps/<slug>` de um sistema existente, com e sem sessão.

Rollback do modo: `helm upgrade --set routing.mode=ingressroute`; o boot seguinte republica no modo
`ingressroute` e apaga os `HTTPRoute` (`republish_routes`, D6). Só sistemas ativos são republicados:
um sistema em erro ou em provisionamento ganha a rota no modo novo quando voltar a ser publicado. Rollback da versão: a versão anterior não republica rotas no
boot, então, se o modo está em `gateway`, volte antes para `ingressroute` (o boot recria as
`IngressRoute` e apaga os `HTTPRoute`); só então `helm rollback` do portal e reinstalar o Traefik
como release separado.
