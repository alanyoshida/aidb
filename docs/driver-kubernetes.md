# Driver Kubernetes (instalação alternativa, validação local)

← [README](../README.md)

O driver de provisionamento padrão é o Docker ([instalação principal](../README.md#instalação)). Existe também um **driver Kubernetes**
(`APPAIFORGE_PROVISIONING_DRIVER=kubernetes`, capability `container-driver-kubernetes`,
[roadmap etapa 8](roadmap-confinamento-do-agente.md)), que materializa cada sistema como um
Pod — hoje validado só contra um cluster `kind` local, nunca contra um cluster gerenciado real
(EKS/GKE/AKS).

Quando o driver ativo é Kubernetes, o próprio portal (e seu Postgres) também roda dentro do
cluster — instale os dois com o chart Helm em [`deploy/helm/appaiforge-portal/`](../deploy/helm/appaiforge-portal):

```bash
docker build -f deploy/portal.Dockerfile -t appaiforge/portal:0.1.0 .
kind load docker-image appaiforge/portal:0.1.0 --name appaiforge-dev   # nome do cluster kind de validação

helm install appaiforge-portal deploy/helm/appaiforge-portal \
  --namespace appaiforge --create-namespace \
  --kube-context kind-appaiforge-dev
```

O chart instala o Traefik como subchart (`traefik.enabled=true`, padrão), com os CRDs dele e os da
Gateway API. Num cluster que já tem um Traefik, desligue o subchart — ver [Roteamento](#roteamento).
No `kind` de validação, o Traefik roda com `hostNetwork` (ver `deploy/pilot-k8s/`) e precisa de
`deployment.dnsPolicy: ClusterFirstWithHostNet`: sem isso, não resolve o DNS do Service do portal,
que o `forwardAuth` de cada rota `/apps/{slug}` chama ([ADR 0027](adr/0027-sso-oidc-e-identidade-das-apps-por-forwardauth.md)
— sintoma: as apps respondem 500 e o log do Traefik mostra `lookup … server misbehaving`). Ele também
usa rollout `maxSurge: 0`, porque num nó só o pod novo não agenda enquanto o antigo segura as portas
80/443.

Atualizar um portal já instalado que tenha schema criado sem Alembic (sem `alembic_version`): carimbe
a revisão anterior e aplique as novas antes de reiniciar, num pod avulso com a imagem nova —
`alembic stamp b4c5d6e7f8a9 && alembic upgrade head` em `/app/portal`. Detalhes de valores, teardown e o que o chart não cobre (broker de
inferência, telemetria) ficam no [README do chart](../deploy/helm/appaiforge-portal/README.md). Os
manifests antigos, aplicados manualmente com `kubectl apply`, continuam em
`openspec/changes/archive/2026-11-14-deploy-portal-in-cluster/` só como histórico da decisão — o
chart é a forma recomendada de instalar hoje.

## Composição do pod de cada sistema

| Container | Para quê | Monta |
|---|---|---|
| `agent` | supervisor, agente e app gerada | workspace (`/workspace`), config do agente |
| `dbgate` | proxy de gate de banco (só com conexão cadastrada) | — |
| `httpsproxy` | proxy HTTP(S) de saída | — |
| `git` | onde o portal executa git, por `exec` | workspace (`/workspace`) e repositório (`/gitdir`) |

Cada sistema tem dois PVCs: `appaiforge-sys-<slug>-workspace` (árvore de trabalho) e
`appaiforge-sys-<slug>-gitdir` (repositório git, 1 GiB). O container `agent` **não** monta o PVC do
repositório: o histórico de checkpoints fica fora do alcance do agente, e o git do portal nunca roda
no container dele ([segurança](seguranca.md#repositório-git-do-sistema-fora-do-workspace)). O
container `git` usa a imagem base, fica ocioso (`sleep infinity`) e tem a mesma identidade e as
mesmas restrições do `agent`, para os arquivos que uma restauração escreve continuarem do agente.

Pods criados antes do container `git` são recriados pela reconciliação na primeira passada depois
da atualização do portal (a reconciliação roda em segundo plano logo depois da subida e a cada
`APPAIFORGE_RECONCILE_INTERVAL` segundos, ver [configuração](configuracao.md); o mesmo vale para um
Pod removido por fora ou com imagem ou Secrets de pull diferentes da configuração); workspace e histórico ficam nos PVCs e sobrevivem à recriação. Até lá, uma
operação de checkpoint nesse sistema falha com a mensagem "não tem o container 'git'". Arquivar um
sistema preserva os dois PVCs; a exclusão definitiva remove os dois (o `Role` do chart precisa do
verbo `delete` em `persistentvolumeclaims`).

## Roteamento

A rota de cada app (`/apps/{slug}`) segue o modo de roteamento da instalação
(`APPAIFORGE_K8S_ROUTING_MODE`, valor `routing.mode` do chart; change
`gateway-api-traefik-subchart`, [ADR 0032](adr/0032-gateway-api-com-traefik-como-implementacao.md)).
Os dois modos convivem só nesta versão; o `ingressroute` sai numa versão seguinte.

| | `ingressroute` (padrão) | `gateway` |
|---|---|---|
| objetos por sistema | `Middleware` `<nome>-auth` (forwardAuth), `Middleware` `<nome>-strip`, `IngressRoute` `<nome>` | `Middleware` `<nome>-auth` (forwardAuth), `HTTPRoute` `<nome>` |
| reescrita do caminho | `stripPrefix` | filtro `URLRewrite` (`ReplacePrefixMatch: /`), depois do `ExtensionRef` do auth |
| não ser capturada pela rota do portal | prioridade 100 contra 1 | mesmo hostname da rota do portal (`APPAIFORGE_K8S_ROUTE_HOSTNAME`) |
| Gateway | — | `APPAIFORGE_K8S_GATEWAY_NAME` / `_NAMESPACE` |

Nos dois modos a autenticação é o mesmo `Middleware` `forwardAuth`: o `HTTPRoute` o referencia por
um filtro `ExtensionRef`, antes do `URLRewrite`, para o portal ver o caminho original e devolver o
usuário à app depois do login. O Traefik executa os filtros na ordem declarada (verificado no
spike da change).

**Trocar de modo**: mude `routing.mode` e atualize o chart. Logo depois de o portal subir, a
primeira passada da reconciliação (`provisioning.reconcile()`) republica a rota de todo sistema não
arquivado no modo novo e apaga os objetos do outro modo, sem recriar os Pods por causa disso; voltar
é o mesmo caminho. Os objetos de rota são substituídos no lugar (ler e substituir com o
`resourceVersion`), sem apagar antes, para cada republicação não abrir uma janela em que a rota
não existe. Remover a rota de um sistema apaga os objetos dos dois modos.

Um modo desconhecido, ou o modo `gateway` sem o Gateway configurado, impede o portal de subir
(`UnknownRoutingMode` no `ensure_ready()` do driver).
