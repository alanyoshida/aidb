# Proposal

## Why

Sob o driver Kubernetes, o chat real com o agente não funciona: `_harness_url`
([`agent_queue.py:712`](../../../portal/appaiforge/agent_queue.py)) resolve o
endereço do harness pelo DNS da rede Docker, que não existe quando o driver ativo é
Kubernetes e o portal roda fora do cluster (arquitetura atual). O teste E2E da etapa 8
(`test_kubernetes_e2e.py`) passa só porque faz monkeypatch dessa função — nunca exercita
o caminho real. Isso nunca foi escrito como limitação aceita em nenhum artefato da change
`add-kubernetes-driver`: foi achado ao vivo, numa sessão de teste manual, depois da change
já arquivada.

## What Changes

- O portal passa a rodar como workload dentro do cluster quando o driver de
  provisionamento ativo é Kubernetes — **só nesse cenário**; o deploy via
  `docker-compose` usado com o driver Docker continua existindo, sem nenhuma mudança.
- O `Service` que o driver Kubernetes já cria por sistema (hoje só com `app_port`,
  usado por `/apps/{slug}`) ganha também a porta do harness, de forma que o portal,
  rodando dentro do cluster, alcance o harness de cada sistema por DNS de Service —
  sem expor essa porta fora do cluster e sem nenhuma mudança no protocolo HTTP/SSE
  que o harness já fala.
- Os dados operacionais do próprio portal (sistemas, checkpoints, uso de tokens etc.)
  passam a ser persistidos por um Postgres dentro do cluster, com PVC — mesma garantia
  de durabilidade que o Postgres via `docker-compose` já dá hoje.
- O driver Kubernetes passa a autenticar com a API do cluster via a identidade do
  próprio Pod (`ServiceAccount`), além do `kubeconfig` com contexto explícito que já
  usa hoje — necessário porque o portal, agora rodando dentro do cluster, não tem
  mais um arquivo de kubeconfig de host para ler.

## Capabilities

### New Capabilities
(nenhuma)

### Modified Capabilities
- `container-driver-kubernetes`:
  - Nova requirement: o portal alcança o harness de cada sistema via rede interna
    do cluster quando roda dentro dele, sem expor essa porta fora do cluster.
  - Nova requirement: os dados operacionais do próprio portal persistem através de
    recriações do processo do portal, quando o driver Kubernetes está ativo.
  - "Paridade observável entre drivers de provisionamento" passa a citar também a
    capability `agent-harness` entre as que devem se comportar de forma idêntica
    nos dois drivers — hoje só cita `container-lifecycle` e `app-serving`, omissão
    que é, na prática, a lacuna formal que este gap expõe.

## Impact

- **Código**: `appaiforge/agent_queue.py` (`_harness_url`), `appaiforge/drivers/kubernetes_driver.py`
  (`Service` em `publish()`, `_api()`/`_custom_api()` com suporte a config in-cluster),
  `appaiforge/config.py` (nova configuração de autenticação/endereço do Postgres do portal
  quando em cluster).
- **Infraestrutura nova**: manifestos de `Deployment`/`ServiceAccount`/`Role`/`RoleBinding`
  do próprio portal, e `StatefulSet`/`PVC`/`Service` do Postgres dele — paralelos aos
  manifestos já arquivados em `openspec/changes/archive/2026-11-11-add-kubernetes-driver/`
  (`kind-cluster.yaml`, `traefik-values.yaml`).
- **Sem impacto em produção**: `deploy/docker-compose.yml`, `appaiforge-portal-1` e o
  restante do stack real (driver Docker) não mudam.
- **Testes**: `test_kubernetes_e2e.py` deixa de depender do monkeypatch de `_harness_url`
  para validar o chat real.
