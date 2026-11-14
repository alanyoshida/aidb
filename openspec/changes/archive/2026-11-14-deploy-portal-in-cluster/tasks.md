# Tasks

## 1. Harness alcançável pelo `Service` que o driver já cria

- [x] 1.1 Adicionar `harness_port` como uma segunda `ServicePort` ao `Service` criado em
  `publish()` (`kubernetes_driver.py:173-186`), e verificar via teste de integração contra `kind`
  que um cliente HTTP dentro do cluster (outro Pod) alcança o harness do Pod do sistema pelo DNS
  do `Service` (`system_container_name(slug)`), na porta do perfil ativo. Feito:
  `k8s.V1ServicePort(name="harness", port=harness_port, ...)` somado ao `ServicePort` da app
  (ambas com `name=` agora, exigido pelo k8s quando há mais de uma porta no Service). Verificado:
  `test_harness_alcancavel_pelo_service_interno` (`test_kubernetes_driver.py`) — conecta via
  `kubectl exec` no nome do `Service`, não no loopback do Pod.
- [x] 1.2 Rodar a suíte existente do driver Kubernetes (`test_kubernetes_driver.py`,
  `test_driver_parity.py`) e confirmar que nenhum teste quebra com a porta nova no `Service`.
  Verificado: 13/13 passaram.

## 2. `_api()`/`_custom_api()` com suporte a autenticação in-cluster

- [x] 2.1 Implementar o fallback `load_incluster_config()` → `load_kube_config(context=...)` em
  `_api()`/`_custom_api()` (`kubernetes_driver.py:33-45`), logando explicitamente qual caminho foi
  usado na primeira chamada do processo, e verificar com um teste unitário que cobre os dois
  caminhos (mockando a disponibilidade do ambiente in-cluster). Feito: `_load_kube_config()`
  compartilhada por `_api()`/`_custom_api()`. Verificado: `tests/unit/test_kubernetes_auth.py`
  (2 testes, mocka as duas chamadas do SDK).
- [x] 2.2 Verificar que o fluxo de teste manual já usado nesta exploração (processo de host, fora
  do cluster, com `k8s_kubeconfig_context` explícito) continua funcionando sem nenhuma mudança —
  rodar a suíte de integração do driver Kubernetes de fora do cluster, como hoje. Verificado:
  `test_kubernetes_driver.py` + `test_kubernetes_e2e.py` + `test_driver_parity.py`, 14/14 passaram
  (fallback cai pro kubeconfig como antes, já que nenhum `ServiceAccount` está montado no host).

## 3. Deploy do portal dentro do cluster

- [x] 3.1 Escrever o manifesto de `ServiceAccount`+`Role`+`RoleBinding` do portal, com permissão
  mínima sobre Pods/Services/ConfigMaps/PVCs/exec no namespace configurado, e verificar com
  `kubectl auth can-i --as=system:serviceaccount:<ns>:<nome> <verbo> <recurso>` que cobre
  exatamente as operações que o driver Kubernetes já faz, nem mais nem menos. Feito:
  `portal-rbac.yaml` (enumerado lendo `kubernetes_driver.py` + `checkpoints.py` por completo —
  nenhum `list`/`watch`/`patch` é usado em nenhum lugar). `namespaces` fica num
  `ClusterRole`/`ClusterRoleBinding` separado (único recurso cluster-scoped, usado só por
  `ensure_ready()`). Verificado: todo `can-i` esperado = yes, todo fora do escopo (list/update
  pods, get/list services e configmaps, delete PVC, list/delete namespaces) = no.
- [x] 3.2 Escrever o manifesto de `Deployment` do portal (reaproveitando a imagem de
  `deploy/portal.Dockerfile`), com a env equivalente à do `docker-compose` hoje, e verificar que o
  Pod sobe `Running` e `GET /api/health` responde de dentro do cluster (via `kubectl exec` de
  outro Pod, ou `kubectl port-forward` de sessão). Feito: `portal-deployment.yaml` (Deployment +
  Service `appaiforge-portal`; env também fixa `APPAIFORGE_PORTAL_INTERNAL_URL` pro DNS do
  Service, substituindo o default Docker-net `http://portal:8080` — achado ao escrever a env: os
  sidecars `dbgate` de cada sistema chamam essa URL de volta pro portal). Imagem construída
  (`docker build -f deploy/portal.Dockerfile`) e carregada no `kind`
  (`kind load docker-image appaiforge/portal:0.1.0`). Verificado: `rollout status` completo, `GET
  /api/health` de dentro do cluster responde 200.
- [x] 3.3 Confirmar que, com o portal rodando dentro do cluster, o driver resolve corretamente o
  caminho in-cluster (task 2.1) sem precisar de `k8s_kubeconfig_context` configurado, e verificar
  via log do processo qual caminho de autenticação foi usado. Verificado via `kubectl exec` no
  Pod do portal: log `driver Kubernetes autenticado via in-cluster (ServiceAccount do Pod)`, e
  `read_namespace('appaiforge')` funciona de verdade (RBAC da task 3.1 confirmado em uso real).

## 4. Postgres do portal dentro do cluster

- [x] 4.1 Escrever o manifesto de `StatefulSet`+PVC+`Service` (`ClusterIP`) do Postgres do portal,
  e verificar que o PVC entra em `Bound` e que outro Pod do namespace alcança o Postgres pelo DNS
  do `Service` (`pg_isready` via `kubectl exec`). Feito: `portal-postgres.yaml` (Service
  headless, `StatefulSet` com `volumeClaimTemplates`). Verificado contra `kind`: PVC `Bound`
  (`data-appaiforge-portal-postgres-0`, 1Gi); `pg_isready -h appaiforge-portal-postgres` de um
  Pod efêmero separado responde "accepting connections".
- [x] 4.2 Apontar a env `APPAIFORGE_DATABASE_URL` do `Deployment` do portal (task 3.2) para o
  `Service` deste Postgres, e verificar que o portal sobe sem erro e aplica o schema esperado
  (mesma verificação que `docker-compose` já faz hoje). Feito junto da task 3.2 (env já escrita
  apontando pro Service certo). Verificado: `\dt` no Postgres em cluster mostra todas as tabelas
  (`agent_runs`, `checkpoints`, `systems`, etc.) — `Base.metadata.create_all()` do boot do portal
  rodou com sucesso.
- [x] 4.3 Escrever um teste (ou roteiro manual documentado) que cria um sistema, recria o Pod do
  portal, e verifica que o sistema continua presente na listagem depois — confirmando a
  requirement "Persistência dos dados operacionais do portal quando o driver é Kubernetes".
  Verificado ao vivo contra `kind`: criado sistema `teste-persistencia-cluster` via `kubectl exec`
  no Pod do portal, `kubectl delete pod` (não o Deployment) força recriação — novo Pod (nome
  diferente), `get_system_by_slug` continua encontrando o mesmo sistema.

## 5. Chat real e paridade com `agent-harness`

- [x] 5.1 Rodar o fluxo de chat real (enviar prompt, receber streaming de eventos, interromper)
  contra um sistema provisionado pelo driver Kubernetes, com o portal rodando de dentro do
  cluster via o `Deployment` da task 3.2 — sem nenhum monkeypatch de `_harness_url`. Substituir o
  monkeypatch em `test_kubernetes_e2e.py` por esse caminho real, e verificar que o teste passa sem
  ele. Feito: novo teste `test_sistema_k8s_ponta_a_ponta_com_portal_dentro_do_cluster` — exec um
  script real dentro do Pod do `Deployment` `appaiforge-portal` (sem port-forward, sem
  monkeypatch; `get_queue()` usa o `_harness_url` real). O teste host-driven original
  (`test_sistema_k8s_ponta_a_ponta_com_checkpoint`, com port-forward) continua existindo —
  cobre a outra topologia ainda suportada (portal fora do cluster, fallback kubeconfig da task
  2.1), não foi retirada. Achado real ao validar (corrigido antes de reportar a task como
  concluída): `connect_get_namespaced_pod_exec` exige verbo RBAC `get` em `pods/exec`, não
  `create` como a task 3.1 tinha assumido — corrigido em `portal-rbac.yaml`. Verificado: teste
  passa, 1/1.
- [x] 5.2 Confirmar que `test_harness_e_sidecars_nao_alcancaveis_de_fora_do_cluster` continua
  passando com a porta nova no `Service` (task 1.1) — a porta do harness deve seguir inalcançável
  de fora do cluster, só a do `Service` interno muda. Verificado: passa (1/1) — conecta direto no
  IP do Pod a partir do host real, não pelo `Service`, então a porta nova não muda esse teste.
- [x] 5.3 Rodar a suíte completa de testes unitários e de integração do portal (Docker +
  Kubernetes) e confirmar que o resultado é idêntico ao obtido antes desta change para o driver
  Docker — nenhuma regressão. Verificado: 450 passaram, 1 falhou
  (`test_portal_responde_via_edge`, falha pré-existente de ambiente — Traefik fora do ar no
  stack de teste e2e, confirmada reproduzível também sem as mudanças desta change). 450 = 446 da
  suíte antes desta change + 4 testes novos (`test_kubernetes_auth.py` ×2,
  `test_harness_alcancavel_pelo_service_interno`,
  `test_sistema_k8s_ponta_a_ponta_com_portal_dentro_do_cluster`).

## Workflow follow-up

- ~~Atualizar `docs/roadmap-confinamento-do-agente.md` registrando que o gap do `_harness_url`
  (achado fora de qualquer etapa numerada, depois da etapa 8 já arquivada) foi corrigido por esta
  change.~~ Feito.
- Arquivar esta change (`/opsx:archive`) depois da revisão, sincronizando a spec
  `container-driver-kubernetes` (modificada: duas requirements novas, "Paridade observável" com
  `agent-harness` incluída).
