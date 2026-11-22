# 0032 — Gateway API com o Traefik como implementação, subchart do Traefik e dois modos de roteamento transitórios

* Status: aceito
* Data: 2026-11-22
* Decidida em: change `gateway-api-traefik-subchart` (design D0, D1, D3, D4)
* Fecha: a "Pendência futura — Gateway API" da etapa 8 do [roadmap de confinamento](../roadmap-confinamento-do-agente.md)
* Relacionado: [0027](0027-sso-oidc-e-identidade-das-apps-por-forwardauth.md)

## Contexto

No driver Kubernetes, a rota de cada app (`/apps/<slug>`) e a do portal eram CRDs do Traefik (`IngressRoute` e `Middleware`), e o Traefik era instalado à parte, sem ser uma dependência declarada do chart. A Gateway API (`HTTPRoute`) é o sucessor padronizado do Ingress.

O acoplamento real ao Traefik não é o `IngressRoute`, e sim o `forwardAuth` do [ADR 0027](0027-sso-oidc-e-identidade-das-apps-por-forwardauth.md): ele confere a sessão a cada requisição (WebSocket incluído), leva ao login e de volta ao caminho pedido, e injeta o `X-AIDB-Identity`. A Gateway API não tem um equivalente estável: o filtro `ExternalAuth` (GEP-1494) ainda é do canal experimental.

## Decisão

1. **Traefik como implementação da Gateway API.** No modo `gateway`, cada sistema tem um `HTTPRoute` com dois filtros, nesta ordem: `ExtensionRef` para o `Middleware` `forwardAuth` (o mesmo de antes) e `URLRewrite` com `ReplacePrefixMatch: /` (no lugar do `stripPrefix`). O `ExtensionRef` é o único ponto da rota preso ao Traefik. Verificado num cluster de teste: o Traefik 3.7.17 executa os filtros na ordem declarada, e o portal recebe o caminho original no `X-Forwarded-Uri`. As rotas das apps levam o mesmo hostname da rota do portal: a especificação dá precedência ao hostname mais específico, e sem isso a rota `/` do portal capturaria `/apps/*` (o Traefik 3.7.17 não aplica essa regra, mas a especificação aplica).
2. **Traefik como subchart do chart do portal**, ligado por padrão (`traefik.enabled`), com os providers de CRDs e de Gateway API. O `Gateway` é do chart do portal, não do subchart, para o chart controlar nome, listeners e TLS. Com o subchart desligado, as rotas se ligam a um `Gateway` existente (`gateway.existing`).
3. **CRDs da Gateway API no chart do portal.** O chart do Traefik 42.3.2 não os traz. O chart do portal traz em `crds/` os CRDs do canal standard v1.6.3, a versão que o Traefik pede, sem a `ValidatingAdmissionPolicy` `safe-upgrades` do mesmo arquivo de release, que não é CRD e é política de cluster. O Helm os instala só no `helm install`: atualizá-los, e aplicá-los ao atualizar com `helm upgrade` uma instalação anterior a esta decisão, são passos manuais do guia de operação.
4. **Dois modos de roteamento, transitórios** (`routing.mode`): `ingressroute` (padrão desta versão, as rotas de antes) e `gateway`. Trocar o modo republica, no boot seguinte do portal, as rotas dos sistemas ativos e apaga as do outro modo, sem recriar Pods. O boot ganhou essa republicação nesta change porque a reconciliação de containers (`provisioning.reconcile()`), que as specs descrevem como "ao iniciar", não era chamada pelo portal em execução. *Atualização:* a change `portal-reconcile-loop` passou a rodar a reconciliação logo depois da subida e periodicamente; a primeira passada publica a rota de todo sistema não arquivado, e a republicação própria do boot (`republish_routes()`) foi removida. Uma change seguinte remove o modo `ingressroute` e passa o padrão para `gateway`, quando o modo `gateway` estiver validado no piloto.

## Alternativas consideradas

- **Filtro `ExternalAuth` padrão da Gateway API**: é o equivalente certo do `forwardAuth`, mas está no canal experimental e o suporte entre controladores é desigual. Fica para quando estiver estável.
- **Sidecar de autenticação no Pod de cada sistema**: tiraria a autenticação da borda e funcionaria com qualquer controlador, inclusive os gerenciados das nuvens, que não fazem `forwardAuth`. Descartado agora: muda o modelo de ameaça (a app passaria a precisar de NetworkPolicy para não ser alcançada sem passar pelo sidecar) e quebra a paridade com o driver Docker. É o caminho se o alvo deixar de ser o Traefik.
- **Traefik como pré-requisito verificado, sem subchart**: deixaria o controlador, que é de escopo de cluster, com quem administra o cluster. Preferiu-se a instalação de um passo; o subchart desligável cobre o cluster compartilhado.
- **Corte direto para `HTTPRoute`, sem modo de transição**: quebraria toda instalação Kubernetes de uma vez, e voltar exigiria `helm rollback`.

## Consequências

- O chart do portal instala, por padrão, componentes de escopo de cluster: os CRDs do Traefik e da Gateway API, o `GatewayClass` `traefik` e a ClusterRole do Traefik. Quem não quiser isso desliga `traefik.enabled`.
- Quem já tinha o Traefik como release à parte precisa desinstalá-lo antes de atualizar, ou usar `traefik.enabled=false`; os dois Traefik disputariam as mesmas portas.
- O portal continua preso ao Traefik pela autenticação, nos dois modos. A Gateway API padroniza o roteamento, não a autenticação.
- Enquanto os dois modos existirem, os testes do chart, do driver e de integração rodam nos dois.
