# Tasks

## 1. Spikes no kind (antes de qualquer código)

Num cluster `kind` descartável, com o chart `traefik/traefik` 42.3.2 e os providers
`kubernetesGateway` + `kubernetesCRD` ligados, uma app de eco e um `Middleware` `forwardAuth`
de teste. Registrar o resultado de cada spike numa seção "Resultados dos spikes" do `design.md`.

- [x] 1.1 S1 — ordem dos filtros: um `HTTPRoute` com `[ExtensionRef auth, URLRewrite
  ReplacePrefixMatch /]` e verificar que o serviço de auth recebe `X-Forwarded-Uri` com o caminho
  **original** (`/apps/x/relatorios`) e que a app recebe o caminho reescrito (`/relatorios`). Se
  falhar, validar o recuo de D1 (`ExtensionRef` para um `Middleware` `chain [auth, stripPrefix]`)
  e atualizar D1 com o caminho escolhido.
- [x] 1.2 S2 — precedência: um `HTTPRoute` `host: aidb.test` + `PathPrefix /` e outro
  `host: aidb.test` + `PathPrefix /apps/x`, e verificar que `aidb.test/apps/x` chega à app e
  `aidb.test/` ao "portal". Repetir com a rota da app **sem** hostname e registrar que `/` a captura
  (confirma a necessidade de D2).
- [x] 1.3 S3 — CRDs: verificar se o chart 42.3.2 instala os CRDs da Gateway API (e qual versão e
  canal), e que o Traefik com os dois providers ligados sobe e serve `IngressRoute` normalmente
  com os CRDs presentes e nenhum `Gateway`. Atualizar D4 com a fonte dos CRDs escolhida.
- [x] 1.4 S4 — WebSocket: abrir uma conexão WebSocket pela rota do S1 com o `forwardAuth`
  aprovando e recusando, e verificar o upgrade nos dois casos (estabelece / recusa).

## 2. Chart: subchart do Traefik, modo de roteamento e `Gateway`

- [x] 2.1 Declarar `traefik/traefik` 42.3.2 em `Chart.yaml` com `condition: traefik.enabled`,
  gerar e versionar `Chart.lock` e `charts/traefik-*.tgz`, e verificar que `helm template` funciona
  sem rede (o teste do chart passando com a rede desligada).
- [x] 2.2 Em `values.yaml`, bloco `traefik` (padrão `enabled: true`, providers `kubernetesGateway`
  e `kubernetesCRD` ligados, `kubernetesIngress` desligado, `Gateway` padrão do subchart desligado),
  `routing.mode` (padrão `ingressroute`) e bloco `gateway` (`existing.name`, `existing.namespace`);
  verificar com `helm template` que os objetos do Traefik aparecem com o padrão e somem com
  `traefik.enabled=false`.
- [x] 2.3 Validar `routing.mode` no template (`fail` com a lista de modos aceitos) e passá-lo ao
  portal como `APPAIFORGE_K8S_ROUTING_MODE` em `templates/deployment.yaml`; cobrir em
  `test_helm_chart.py` o padrão, `gateway` e um valor inválido.
- [x] 2.4 Se o S3 concluiu que os CRDs não vêm do subchart, adicionar os CRDs da Gateway API
  (canal standard, versão suportada pelo Traefik) em `crds/` do chart e verificar que
  `helm template --include-crds` os lista.
- [x] 2.5 Criar `templates/gateway.yaml` (D3), só no modo `gateway` com `traefik.enabled`:
  `gatewayClassName: traefik`, listener `web` e, com `portalRoute.tlsSecretName`, listener
  `websecure` com `certificateRefs`; `allowedRoutes` aceitando o namespace da release e o dos
  sistemas. No modo `gateway` com `traefik.enabled=false`, `required` para
  `gateway.existing.name` e `.namespace`. Cobrir em `test_helm_chart.py`: padrão não cria
  `Gateway`; `gateway` cria; com TLS tem o listener HTTPS; `gateway` desligado sem
  `gateway.existing` falha com mensagem; `gateway` desligado com `gateway.existing` não cria
  `Gateway`; `ingressroute` desligado não exige `gateway.existing`.
- [x] 2.6 Condicionar `templates/ingressroute.yaml` ao modo `ingressroute` (sem outra mudança) e
  criar `templates/httproute-portal.yaml` para o modo `gateway`: `HTTPRoute` com
  `hostnames: [portalRoute.host]`, `PathPrefix /`, `parentRefs` para o `Gateway` (do chart ou
  existente), sem TLS na rota. Parametrizar por modo os testes de rota do portal em
  `test_helm_chart.py` (ligada, ligada com TLS, sem host falha, desligada por padrão) e verificar
  que passam.
- [x] 2.7 Em `templates/deployment.yaml`, no modo `gateway`, passar ao portal
  `APPAIFORGE_K8S_GATEWAY_NAME` e `APPAIFORGE_K8S_GATEWAY_NAMESPACE`, e, com `portalRoute.enabled`,
  `APPAIFORGE_K8S_ROUTE_HOSTNAME`; cobrir os casos em `test_helm_chart.py`.
- [x] 2.8 Em `templates/rbac.yaml`, adicionar `gateway.networking.k8s.io` `httproutes` e, para
  `traefik.io` `middlewares` e `ingressroutes`, os verbos `get`, `create`, `update` e `delete`
  (D5, D6); verificar no `test_helm_chart.py`.
- [x] 2.9 Atualizar `values-production.yaml`, o `README.md` do chart (tabela de valores nova:
  `routing.mode`, `traefik.*`, `gateway.existing.*`) e `NOTES.txt`; verificar que o exemplo de
  produção renderiza com `helm template -f values-production.yaml` nos dois modos.

## 3. Driver Kubernetes: dois modos de rota

- [x] 3.1 Em `config.py`, `k8s_routing_mode` (padrão `ingressroute`), `k8s_gateway_name`,
  `k8s_gateway_namespace` e `k8s_route_hostname` (padrão vazio); o driver Kubernetes levanta erro
  no `ensure_ready()` para modo desconhecido, com os modos aceitos na mensagem. Testes unitários
  dos valores lidos do ambiente e do erro.
- [x] 3.2 Separar `app_route_objects` em dois construtores: o do modo `ingressroute`, que devolve
  exatamente os objetos de hoje (auth, strip, `IngressRoute`), e o do modo `gateway`, que devolve o
  `Middleware` `<nome>-auth` e um `HTTPRoute` `<nome>` com `parentRefs` do `Gateway` configurado,
  `hostnames` só quando `k8s_route_hostname` estiver definido, e os filtros na ordem validada no S1
  (D1). Testes unitários: o modo `ingressroute` gera objetos iguais aos da versão anterior; o modo
  `gateway` com e sem hostname, e a ordem dos filtros.
- [x] 3.3 Trocar o "apagar e recriar" por "ler → substituir com `resourceVersion` → criar se 404"
  para `HTTPRoute`, `IngressRoute` e `Middleware`, com grupo e versão por objeto
  (`gateway.networking.k8s.io/v1`, `traefik.io/v1alpha1`) (D5); teste unitário com um
  `CustomObjectsApi` falso cobrindo objeto existente e ausente, verificando que nenhum `delete` é
  chamado no caminho de publicação.
- [x] 3.4 Em `publish()`, depois de criar os objetos do modo ativo, apagar os do outro modo
  tolerando 404; em `unpublish()`, apagar os objetos dos dois modos tolerando 404 (D6). Testes
  unitários das sequências nos dois modos, incluindo o caso em que só existem os objetos do outro
  modo.
- [x] 3.5 Atualizar as docstrings de `publish`/`app_route_objects` e `docs/driver-kubernetes.md`
  (os dois modos, filtro de auth, hostname, como trocar), e verificar que
  `uv run pytest -n 8 tests/unit tests/bdd` passa.

- [x] 3.6 Republicar no boot do portal a rota de cada sistema ativo sob o driver Kubernetes
  (`provisioning.republish_routes()`, chamado em `create_app`), porque `reconcile()` não roda no
  boot (D6); testes unitários (só ativos, falha num sistema não segura os outros, driver Docker
  não republica) e o teste de integração de troca de modo passando pelo `republish_routes`.

## 4. Piloto, operação, ADR e roadmap

- [x] 4.1 `deploy/pilot-k8s/`: tirar o `helm install traefik` separado do `README.md`, levar o que
  ainda vale de `traefik-values.yaml` (`hostNetwork`, `dnsPolicy`, estratégia de rollout) para os
  valores do subchart no exemplo do piloto, e verificar subindo o piloto do zero pelo README.
- [x] 4.2 `docs/operacao.md`: atualização de uma instalação com Traefik em release separado
  (desinstalar antes, ou `traefik.enabled=false`, com `gateway.existing.*` no modo `gateway`), como
  virar o modo para `gateway` e voltar, atualização manual dos CRDs da Gateway API ao trocar a
  versão do Traefik, e rollback da versão; verificar seguindo os passos no piloto (grupo 5).
- [x] 4.3 Escrever `docs/adr/0032-gateway-api-com-traefik-como-implementacao.md` (contexto,
  decisões D0, D1 e D3, alternativas `ExternalAuth` e sidecar de auth, critério para remover o modo
  `ingressroute`, consequências) e adicioná-lo ao índice `docs/adr/README.md`.
- [x] 4.4 No roadmap, trocar a "Pendência futura — Gateway API" da etapa 8 por uma referência a
  esta change e ao ADR 0032, citando o modo `gateway` como opcional nesta versão.

## 5. Integração no kind

- [x] 5.1 Atualizar `tests/integration/test_kubernetes_driver.py`, `test_kubernetes_e2e.py` e
  `test_driver_parity.py` para rodar nos dois modos (limpeza cobrindo `IngressRoute`, `strip` e
  `HTTPRoute`), e verificar que `uv run pytest tests/integration` passa no kind com o portal
  instalado pelo chart, em cada modo.
- [x] 5.2 Teste de integração do cenário "App e portal no mesmo host", nos dois modos: rota do
  portal ligada com host, `GET <host>/apps/<slug>` chega à app e `GET <host>/` ao portal.
- [x] 5.3 Teste de troca de modo nos dois sentidos: com um sistema publicado no modo
  `ingressroute`, subir o portal com `gateway` e verificar que a app responde em `/apps/<slug>`, que
  o Pod não foi recriado (mesmo `uid`) e que `IngressRoute` e `strip` sumiram; depois voltar para
  `ingressroute` e verificar o mesmo, com o `HTTPRoute` sumindo.
- [x] 5.4 Verificar no kind, pelo E2E Kubernetes existente ou pelo navegador, os cenários de
  `app-serving` nos dois modos: sem sessão volta a `/apps/<slug>/relatorios` depois do login,
  WebSocket da app abre com sessão e é recusado sem, e identidade forjada é descartada.

## Workflow follow-up

- Rodar `node .gitnexus/run.cjs detect-changes --scope all --repo .` antes de cada commit.
- Arquivar a change depois da revisão e sincronizar as specs.
- Change seguinte, depois do modo `gateway` validado no piloto: remover o modo `ingressroute`
  (construtor, template `ingressroute.yaml`, limpeza cruzada de D6, RBAC de `ingressroutes`) e
  passar o padrão de `routing.mode` para `gateway`.
