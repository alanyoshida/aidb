# Design

## Context

Hoje o portal roda como processo de host (via `docker-compose`), inclusive quando o driver de
provisionamento ativo é Kubernetes — o driver fala com a API do cluster a partir de fora dele,
sempre com contexto de kubeconfig explícito
([`kubernetes_driver.py:33-45`](../../../portal/appaiforge/drivers/kubernetes_driver.py)). Isso
funciona para toda operação de controle (criar Pod/Service/ConfigMap/PVC, exec para checkpoints
via [`checkpoints.py:42-56`](../../../portal/appaiforge/checkpoints.py)) porque tudo isso passa pela API do
Kubernetes, que o portal já alcança de fora normalmente.

`_harness_url` ([`agent_queue.py:712-717`](../../../portal/appaiforge/agent_queue.py)) é diferente:
monta um endereço de **dados** (`http://<nome>:<porta>`) usando o DNS da rede bridge do Docker, e é
chamado em toda operação de chat com o agente — criar sessão, enviar prompt, abortar, responder
gate, e abrir o SSE de eventos (`GET /event`, conexão sem fim durante a execução). Essa função não
tem nenhuma abstração de driver; sob o driver Kubernetes, o hostname que ela monta nunca resolve,
porque o portal roda fora do cluster. Isso nunca foi escrito como limitação aceita em nenhum
artefato da change `add-kubernetes-driver` — foi achado ao vivo, numa sessão de teste manual depois
da change já arquivada, e contornado só para aquela sessão (`kubectl port-forward` por sistema +
override de `socket.getaddrinfo`, nunca commitado).

Decisões já fechadas com o usuário (ver conversa de exploração): o portal passa a rodar dentro do
cluster quando o driver ativo é Kubernetes; o harness é alcançado via o `Service` que o driver já
cria por sistema; o Postgres do portal também entra no cluster, com `StatefulSet` + PVC para
persistência.

## Goals / Non-Goals

**Goals:**
- O portal, rodando dentro do cluster, consegue falar com o harness de cada sistema (chat,
  streaming, abort, gate, perguntas) exatamente como o driver Docker já permite hoje.
- O harness continua inalcançável de fora do cluster — a mudança não abre nenhuma exposição nova.
- Os dados operacionais do próprio portal persistem através de recriações do seu processo, quando
  o driver Kubernetes está ativo.
- Nenhuma mudança no protocolo HTTP/SSE que o harness já fala (`opencode.py`, `claude_code.py`).
- Zero impacto no deploy de produção atual (`docker-compose`, driver Docker).

**Non-Goals:**
- Migrar o deploy de produção (driver Docker) para dentro de um cluster — fora de escopo,
  decisão explícita do usuário nesta exploração.
- Cluster gerenciado real (EKS/GKE/AKS) — ainda não é objetivo, mesmo non-goal herdado da etapa 8
  (`add-kubernetes-driver`); continua só `kind` local.
- Múltiplas réplicas ou alta disponibilidade do portal — permanece um único processo, igual hoje.
- Estratégia de backup/restore do Postgres em cluster — preocupação operacional, não
  comportamento observável do sistema.
- Migração de dados de um Postgres `docker-compose` existente para o novo — não se aplica: o
  driver Kubernetes só foi validado em `kind` local, sem nenhum sistema real provisionado por ele
  (confirmado no teardown desta mesma sessão de exploração).

## Decisions

### D1 — Harness alcançado por uma porta nova no `Service` que o driver já cria, não um objeto novo
`publish()` ([`kubernetes_driver.py:160-186`](../../../portal/appaiforge/drivers/kubernetes_driver.py))
já cria, na hora do provisionamento (chamado de dentro de `provision_system`,
[`provisioning.py:449`](../../../portal/appaiforge/provisioning.py)), um `Service` nomeado
`system_container_name(slug)` — a mesma string que `_harness_url` já usa como hostname. Adicionar
`harness_port` como uma segunda `ServicePort` nesse mesmo objeto faz esse hostname resolver de
verdade via DNS de Service do Kubernetes, sem mudar nada na lógica de `_harness_url` além de onde
ela roda. Alternativa rejeitada: um `Service` dedicado só para o harness — mais um objeto Kubernetes
por sistema sem ganhar nada sobre reaproveitar o que já existe.

### D2 — `ClusterIP` (tipo padrão), sem `IngressRoute` nem Middleware nova
A requirement já existente "harness inacessível de fora do cluster" continua satisfeita de
graça: um `Service` tipo `ClusterIP` não é roteável de fora do cluster, diferente do
`IngressRoute` que `publish()` já cria para `app_port`. A fronteira de confiança volta a ser "estar
na rede do cluster" — o mesmo papel que "estar na rede Docker" tinha antes. Nenhuma autenticação
nova é necessária no protocolo do harness (que não tem nenhuma hoje) porque o próprio tipo do
`Service` já restringe o alcance.

### D3 — `_api()`/`_custom_api()` tentam config in-cluster primeiro, com fallback pro kubeconfig
[`kubernetes_driver.py:33-45`](../../../portal/appaiforge/drivers/kubernetes_driver.py) passa a
tentar `load_incluster_config()` (identidade do `ServiceAccount` do próprio Pod) primeiro, caindo
para `load_kube_config(context=...)` só se isso falhar — preserva o fluxo de teste manual deste
host (`run_portal.py`, usado nesta mesma sessão) e qualquer debug futuro feito de fora do cluster,
sem exigir um segundo caminho de código mantido separadamente. Alternativa rejeitada: só config
in-cluster, sem fallback — quebraria o fluxo de teste manual já validado nesta sessão.

### D4 — Postgres do portal como `StatefulSet` + PVC, `Service` `ClusterIP` próprio
Decisão do usuário. Mesmo racional do D2: só o portal precisa alcançar esse Postgres, então
`ClusterIP` sem exposição externa. `StatefulSet` em vez de `Deployment` porque dá identidade
estável ao volume (mesmo PVC sempre que o Pod é recriado) pela convenção correta pra "um banco com
estado" — não por necessidade estrita nesta etapa, já que não há múltiplas réplicas previstas
(Non-Goals).

### D5 — Sem migração de dados do Postgres `docker-compose`
Como isto só vale quando o driver ativo é Kubernetes — ainda só validado em `kind` local, sem
nenhum sistema real provisionado por ele — não existe dado de produção para migrar. O Postgres do
`docker-compose` continua intocado, servindo o driver Docker e o stack real
(`appaiforge-portal-1` etc.).

## Risks / Trade-offs

- **[Risco] Dois caminhos de autenticação em `_api()` (in-cluster vs. kubeconfig) podem mascarar
  erro de configuração silenciosamente** (cai pro caminho errado sem avisar) → Mitigação: logar
  explicitamente qual caminho foi usado, na primeira chamada do processo.
- **[Trade-off] Mais um `StatefulSet`/PVC pra operar, só para validação em `kind`** → Aceito,
  mesma categoria de trade-off do D3 da change `add-kubernetes-driver` (PVC do workspace).
- **[Risco] `kind` difere de um cluster gerenciado real o bastante pra esconder problemas de DNS
  de Service** → Mitigação inalterada, herdada da etapa 8: fora de escopo revisitar isso agora;
  reavaliar antes de qualquer cluster gerenciado real.

## Migration Plan

- Rollout: a porta do harness se soma ao `Service` que já existe (nenhuma mudança de
  comportamento para o driver Docker); o portal-em-cluster é um modo de deploy novo, atrás da
  mesma configuração de driver que já existe hoje — enquanto o driver ativo é Docker, nada muda.
- Rollback: parar de usar o `Deployment` do portal em cluster e voltar a rodar o portal como
  processo de host, igual era antes desta change — sem efeito em nenhum sistema já provisionado
  por Docker.

## Open Questions

- Acesso administrativo externo ao Postgres do portal em cluster (ex.: inspecionar o banco de
  fora para debug) — não resolvido aqui; se necessário, é um `kubectl port-forward` de sessão,
  igual ao workaround já usado nesta exploração, não uma exposição permanente.
