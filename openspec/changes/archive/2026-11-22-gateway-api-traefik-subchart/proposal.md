# Proposal

## Why

No driver Kubernetes, a rota de cada app (`/apps/{slug}`) e a rota do próprio portal são CRDs
específicos do Traefik (`IngressRoute` + `Middleware`), e o Traefik é instalado à parte, por fora
do chart, sem ser uma dependência declarada. A pendência da etapa 8 do roadmap de confinamento
pede a Gateway API no lugar disso. A exploração mostrou que o acoplamento real não é o
`IngressRoute`, e sim o `forwardAuth` (sessão, login com volta ao caminho original e injeção do
`X-AIDB-Identity`), que nenhum padrão estável da Gateway API substitui hoje. A decisão é assumir o
Traefik como implementação da Gateway API e como dependência formal do chart, padronizando o
roteamento sem trocar o mecanismo de autenticação, com uma versão de transição em que os dois
modos de roteamento convivem.

## What Changes

- O chart `appaiforge-portal` passa a declarar o Traefik como **subchart**, ligado por padrão
  (`traefik.enabled`), com os providers de Gateway API e de CRDs ativos.
- Novo **modo de roteamento** (`routing.mode`), transitório, escolhido na instalação:
  - `ingressroute` (padrão nesta versão): as rotas continuam exatamente como hoje (`IngressRoute`,
    `Middleware` de `stripPrefix` e `forwardAuth`, prioridade explícita). Atualizar sem mudar nada
    não muda o roteamento.
  - `gateway`: cada sistema passa a ter um `HTTPRoute` com dois filtros, nesta ordem: `ExtensionRef`
    para o `Middleware` `forwardAuth` (mantido) e `URLRewrite` com `ReplacePrefixMatch` (no lugar do
    `stripPrefix`). A rota do portal vira `HTTPRoute`, e as rotas das apps carregam o mesmo
    hostname dela, para que `/apps/{slug}` continue vencendo `/` sem prioridade explícita.
- No modo `gateway`, com o subchart ligado, o chart cria um `Gateway` (listeners HTTP/HTTPS, TLS no
  listener). Com o subchart desligado, o chart liga as rotas, por `parentRefs`, a um `Gateway`
  Traefik já existente, informado nos valores.
- A troca de modo, nos dois sentidos, acontece sem reprovisionar: o portal republica as rotas dos
  sistemas ativos no modo novo e apaga os objetos do outro modo. A remoção da rota de um sistema
  apaga os objetos dos dois modos.
- O RBAC do portal ganha `httproutes` (`gateway.networking.k8s.io`) e mantém `ingressroutes` e
  `middlewares`.
- `Chart.lock` e o pacote do subchart ficam versionados, para o teste do chart continuar offline.
- O driver Docker não muda: continua no file provider do Traefik.
- Fora desta change: uma change seguinte remove o modo `ingressroute` e passa o padrão para
  `gateway`.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `container-driver-kubernetes`: a publicação de `/apps/{slug}` passa a seguir o modo de
  roteamento da instalação; no modo `gateway`, pela Gateway API ligada ao `Gateway` da instalação.
  Nos dois modos a rota da app não é capturada pela do portal e a autenticação é preservada, e a
  troca de modo não exige reprovisionamento.
- `portal-installation`: o chart instala o controlador de entrada por padrão (subchart Traefik e,
  no modo `gateway`, o `Gateway`), aceita um `Gateway` existente com o subchart desligado, expõe o
  modo de roteamento, e a rota do próprio portal segue o modo escolhido.

## Impact

- **Código**: `portal/appaiforge/drivers/kubernetes_driver.py` (`publish`, `unpublish`,
  `app_route_objects`, `_upsert_custom`) e `portal/appaiforge/config.py` (modo de roteamento,
  hostname e `Gateway` das rotas).
- **Chart**: `deploy/helm/appaiforge-portal/` (`Chart.yaml`, `Chart.lock`, `charts/`, `values.yaml`,
  `values-production.yaml`, `templates/ingressroute.yaml` condicionado ao modo, novos
  `templates/httproute-portal.yaml` e `templates/gateway.yaml`, `templates/rbac.yaml`,
  `templates/deployment.yaml`, `README.md`, `NOTES.txt`).
- **Piloto e documentação**: `deploy/pilot-k8s/` (Traefik deixa de ser release separado),
  `docs/driver-kubernetes.md`, `docs/operacao.md`, roadmap (pendência da etapa 8) e um ADR novo.
- **Testes**: `portal/tests/unit/test_helm_chart.py`, `portal/tests/integration/test_kubernetes_driver.py`,
  `test_kubernetes_e2e.py`, `test_driver_parity.py`, nos dois modos.
- **Dependências**: chart `traefik/traefik` (versão fixada) e os CRDs da Gateway API, canal
  standard, instalados nos dois modos.
- **Operação**: o modo padrão não muda o roteamento, mas o subchart ligado por padrão instala um
  Traefik. Quem já tem o Traefik instalado como release separado precisa desinstalá-lo antes de
  atualizar o portal, ou subir com `traefik.enabled=false` (no modo `ingressroute` isso basta; no
  modo `gateway`, também é preciso apontar para um `Gateway` existente).
