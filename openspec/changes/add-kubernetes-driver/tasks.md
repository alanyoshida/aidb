# Tasks

## 1. Extração da interface de driver (sem mudar comportamento)

- [x] 1.1 Definir a interface `ProvisioningDriver` (ou nome equivalente) com os métodos que
  `provisioning.py` já implementa implicitamente hoje (`provision_system`,
  `remove_container_if_exists`, `reconcile`, provisionamento dos dois sidecars) e verificar que a
  assinatura cobre tudo que o código Docker atual faz, sem omitir nenhum parâmetro usado
  (resource limits, identidade de execução, bind mounts). Feito: `appaiforge/drivers/base.py`
  (`ProvisioningDriver` Protocol com `ensure_ready`/`provision`/`remove`/`reconcile_one`/
  `refresh_https_allowlist`/`healthcheck_url`, exceções `UnknownDriver`/`ComputeUnitNotFound`).
- [x] 1.2 Mover a lógica Docker-específica de `provisioning.py` para uma implementação concreta
  dessa interface, sem alterar nenhum comportamento, e verificar que a suíte de testes de
  integração existente (`portal/tests/integration/`) passa sem nenhuma mudança de asserção.
  Feito: `appaiforge/drivers/docker_driver.py` (`DockerProvisioningDriver`); `provisioning.py`
  mantém só a orquestração agnóstica (env/config/manifesto) e delega ao driver via `get_driver()`.
  Verificado: 373/373 unit + 36/36 integration passam, idêntico à contagem antes da extração
  (um bug real achado e corrigido no meio do caminho: `provision_system` chamava
  `driver.ensure_ready()` direto em vez do delegator `ensure_network()`, quebrando o monkeypatch
  de `test_session_management.py` — corrigido antes de reportar a task como concluída).
- [x] 1.3 Expor a seleção de driver por configuração da plataforma (nova setting, default
  `docker`) e verificar, via teste unitário, que o driver resolvido a partir da configuração é
  usado em todo ponto de chamada que hoje importa `provisioning.py` direto. Feito:
  `settings.provisioning_driver` (`config.py`) + `appaiforge/drivers/__init__.py:get_driver()`;
  `tests/unit/test_provisioning_driver.py` (10 testes novos) confirma a fábrica e que
  `ensure_network`/`provision_system`/`stop_and_remove`/`healthcheck_url`/
  `refresh_https_allowlist`/`reconcile` todos passam pelo driver resolvido via um `_FakeDriver`
  gravando chamadas, sem reimplementar os testes Docker-específicos já existentes.

## 2. Ambiente de validação: cluster `kind` local

- [x] 2.1 Escrever a configuração de cluster `kind` (arquivo YAML do change) com
  `extraPortMappings` expondo as portas do Ingress ao host, e verificar que `kind create cluster
  --config <arquivo>` sobe um cluster utilizável (`kubectl get nodes` mostra o nó `Ready`).
  Feito: `kind-cluster.yaml` (cluster `appaiforge-dev`). Achado real: portas 8080/8443 já estavam
  ocupadas por outros serviços deste ambiente (`wcui-caddy`) — usa 18080/18443 em vez disso.
  Verificado: nó `Ready` em ~25s.
- [x] 2.2 Confirmar a StorageClass default do cluster (`standard`, via
  `local-path-provisioner`) e verificar com um PVC de teste que ele entra em `Bound` sem
  provisionador adicional. Verificado: PVC de 64Mi + Pod consumidor (a StorageClass usa
  `WaitForFirstConsumer`) — `Bound`, escrita real confirmada via `kubectl exec`.
- [x] 2.3 Documentar os comandos de setup/teardown do cluster de teste num README do change (ou
  em `docs/`), e verificar seguindo o próprio documento do zero (cluster novo, nenhum passo
  implícito). Feito: `README.md` do change. Verificado: `kind delete cluster` + recriação seguindo
  só os comandos do documento, do zero — nó `Ready`, StorageClass presente, sem passo implícito.

## 3. Driver Kubernetes — Pod por sistema

- [x] 3.1 Implementar a criação do Pod de um sistema com os três containers (agente, `dbgate`,
  `httpsproxy`) no mesmo Pod, replicando a identidade de execução (`cap_drop`/`no-new-privileges`/
  usuário não-root) via `securityContext`, e verificar via `kubectl exec` que o `id` dentro do
  container do agente bate com o modo de execução do sistema (igual ao teste já feito para o
  driver Docker). Feito: `appaiforge/drivers/kubernetes_driver.py`
  (`KubernetesProvisioningDriver.provision`). Achado real: a imagem só existe no Docker do host,
  não no containerd do nó `kind` — precisa de `kind load docker-image` antes de qualquer Pod
  conseguir subir (documentado no README). Verificado:
  `test_container_do_agente_roda_com_identidade_reduzida` — `id` dentro do container mostra
  `uid=1000`.
- [x] 3.2 Verificar, com um teste de integração contra o cluster `kind`, que um sidecar do Pod
  alcança o container do agente por um endereço loopback (requirement "Sidecar alcança o agente
  por loopback" da capability `container-driver-kubernetes`). Feito:
  `test_sidecar_alcanca_agente_por_loopback` (`tests/integration/test_kubernetes_driver.py`) —
  `kubectl exec` no container `agent` conecta em `127.0.0.1:15500` (porta do sidecar
  `httpsproxy`, mesmo Pod) sem nenhuma config de rede explícita.
- [x] 3.3 Implementar `remove_container_if_exists` equivalente para o driver Kubernetes (deletar o
  Pod do sistema) e verificar que a remoção é idempotente (chamar duas vezes não falha). Feito:
  `KubernetesProvisioningDriver.remove`. Verificado: `test_remove_e_idempotente`.

**Achado real que exigiu correção antes de qualquer teste passar**: `_api()` carregava o
kubeconfig sem `context` explícito, dependendo do `current-context` do arquivo — que mudou entre
dois passos manuais desta mesma sessão (sem nenhuma ação deste driver), fazendo a primeira rodada
de testes criar os objetos no cluster `poc-secure-sdlc` (pré-existente, não relacionado) em vez de
`appaiforge-dev`. Corrigido: `settings.k8s_kubeconfig_context` fixo, nunca o contexto implícito.

## 4. Driver Kubernetes — armazenamento persistente

- [x] 4.1 Implementar a criação do PVC de workspace e do ConfigMap de config por sistema (D3 do
  design, refinado durante a task 3: PVC só pro workspace, ConfigMap pro config — um PVC de
  cluster não é escrevível pelo portal) e verificar que o Pod monta os dois nos caminhos
  esperados (`/workspace`, `/opencode-config`). Feito e verificado via
  `test_provision_system_cria_pod_com_tres_containers` + inspeção `kubectl describe pod` (mounts
  corretos nos dois caminhos).
- [x] 4.2 Escrever e rodar um teste de integração que recria o Pod de um sistema (deleta e
  recria) e verifica que um arquivo gravado no workspace antes da recriação continua presente
  depois (requirement "Workspace sobrevive à recriação do Pod"). Feito:
  `test_workspace_sobrevive_a_recriacao_do_pod`.

## 5. Driver Kubernetes — roteamento de app

- [x] 5.1 Decidir, durante a implementação (D4 do design: Ingress nativo do Traefik vs. file
  provider apontando pro cluster) e implementar o roteamento de `/apps/{slug}` até o Pod do
  sistema, e verificar via `curl` de fora do cluster (pela porta exposta por `extraPortMappings`
  do `kind`) que a app responde. Decisão: `IngressRoute`+`Middleware` nativos do Traefik (CRD),
  não o core `Ingress` — espelha 1:1 o router/middleware/service que o file provider do driver
  Docker já escreve hoje, em vez de reconstruir path-stripping só com anotações. Traefik
  reinstalado via Helm com `hostNetwork: true` + `providers.kubernetesCRD.enabled: true`
  (`traefik-values.yaml` do change), escutando direto nas portas 80/443 do nó — as mesmas que
  `kind-cluster.yaml` já mapeia pro host (18080/18443). `edge.py`'s `publish_app`/`unpublish_app`
  passaram a delegar ao driver ativo (`get_driver().publish/unpublish`); a implementação Docker
  (renomeada `publish_app_docker`/`unpublish_app_docker`) ficou idêntica, só chamada de outro
  lugar — confirmado sem regressão (36/36 integração Docker, 383/383 unit). Achado real: os
  informers de Service e de IngressRoute do provider CRD do Traefik observam eventos
  separadamente — um 404 transitório pode ocorrer entre criar o Service e o IngressRoute ser
  reconciliado, mesmo com o Service já persistido; não é um bug do driver, só exige retry no
  teste (e, na prática, no primeiro acesso logo após provisionar). Verificado:
  `test_publish_app_roteia_pelo_ingress_externo` — `curl` de fora do cluster, pela porta do host.
- [x] 5.2 Verificar que a porta do harness do agente e as portas dos sidecars não são alcançáveis
  de fora do cluster (tentativa de conexão direta falha), confirmando o requirement "Harness e
  sidecars não alcançáveis de fora do cluster". Verificado:
  `test_harness_e_sidecars_nao_alcancaveis_de_fora_do_cluster` — nenhum Service expõe essas
  portas, e o IP do Pod (rede do CNI) não é roteável a partir do host real.

## 6. Driver Kubernetes — limites de recursos

- [x] 6.1 Mapear os limites padrão de CPU/memória/disco configurados para `resources.limits` do
  container do agente no Pod, e verificar via `kubectl describe pod` que os limites aplicados
  batem com a configuração da plataforma. Feito: `_resource_requirements` em
  `kubernetes_driver.py`. Verificado: `test_limites_de_recursos_mapeados_para_o_pod` (cpu, memória
  e `ephemeral-storage` conferem com `settings.container_cpus/_mem_mb/_disk_gb` — a API do k8s
  normaliza a unidade devolvida, ex. `2048Mi` → `2Gi`, por isso a comparação é numérica).
- [x] 6.2 Registrar explicitamente (comentário no código do driver + nota na capability já
  escrita) que `pids_limit` não tem bloqueio rígido por container nesta implementação (D5 do
  design), e verificar que a ausência dessa garantia não quebra nenhum teste existente que
  dependa dela (buscar por `pids_limit` nos testes do driver Docker e confirmar que o driver
  Kubernetes não tenta reusar essa mesma asserção). Feito: docstring de `_resource_requirements`.
  Verificado: a única asserção de `pids_limit` no repo (`test_llm_provisioning.py:479`) testa
  especificamente os kwargs do driver Docker, nunca exercitada pelo driver Kubernetes.

## 7. Driver Kubernetes — reconciliação

- [x] 7.1 Implementar `reconcile()` para o driver Kubernetes via polling contra a API (D6 do
  design: lista Pods esperados vs. reais), e verificar com um teste de integração que deletar
  manualmente o Pod de um sistema ativo e rodar a reconciliação recria o Pod. Feito:
  `KubernetesProvisioningDriver.reconcile_one` (já escrito na task 3, reaproveitado aqui sem
  mudança — `provisioning.reconcile()` já era driver-agnóstico desde o grupo 1) + `ApiException`
  404 → `ComputeUnitNotFound` → `provision_system` recria. Verificado:
  `test_reconciliacao_recria_pod_deletado_manualmente` — Pod deletado manualmente, `reconcile()`
  roda, um Pod NOVO (UID diferente) aparece no lugar.

## 8. Paridade entre drivers e testes end-to-end

- [x] 8.1 Escrever um teste de integração parametrizado (ou dois testes equivalentes) que
  provisiona o mesmo cenário de sistema nos dois drivers e verifica o mesmo resultado observável
  via `app-serving`/`container-lifecycle` (app acessível, workspace persistente, reconciliação
  funcionando) — confirmando o requirement "Paridade observável entre drivers de
  provisionamento". Feito: `tests/integration/test_driver_parity.py`,
  `test_paridade_provisionar_publicar_e_reconciliar[docker|kubernetes]` — mesmo roteiro
  (provision → publish → reconcile_one → remove → reconcile() recria → reconcile_one de novo),
  só através da interface comum (`provisioning.py` + `get_driver()`), nunca de SDK específico.
- [x] 8.2 Rodar a suíte completa de testes unitários e de integração do portal com o driver
  Docker como default (sem mudança de comportamento esperada) e verificar que o resultado é
  idêntico ao obtido antes desta change. Verificado: 384/384 unit (373 antes desta change + 11
  novos testes de driver/sandbox) e 36/36 integração Docker (mesma contagem de antes), em várias
  rodadas ao longo da implementação — nenhuma mudança de comportamento no driver Docker.
- [x] 8.3 Rodar o fluxo completo (criação de sistema → geração real de app via agente → acesso
  via `/apps/{slug}`) contra o cluster `kind`, de ponta a ponta, e verificar que funciona sem
  nenhuma intervenção manual fora do que o driver automatiza. Feito:
  `tests/integration/test_kubernetes_e2e.py::test_sistema_k8s_ponta_a_ponta_com_checkpoint` —
  Pod real, shim real, CLI `claude` real, stub de LLM real (Pod próprio dentro do cluster),
  harness/fila/checkpoint reais, mesmo critério da etapa 7 (`test_claude_code_e2e.py`).

  **Achados reais, corrigidos durante esta task:**
  1. Checkpoints git não tinham equivalente no driver Kubernetes (`checkpoints.py` roda `git` no
     processo do portal, via path local — só existe pro driver Docker, que compartilha bind
     mount com o container). Resolvido com o usuário: `git` agora roda **dentro do container do
     agente via exec da API do Kubernetes** quando o driver é `kubernetes`
     (`checkpoints._git_via_exec`) — mesmo resultado observável nos dois drivers.
  2. **Bug pré-existente em `apply_landlock`** (`base-image/afsupervisor/sandbox.py`, de antes
     desta change): todo `writable_path` ausente era criado como diretório (`os.makedirs`),
     mesmo quando devia ser um arquivo — o perfil `claude-code` lista `.gitconfig`/`.claude.json`
     /`.bashrc` etc. nessa mesma lista. Nunca disparado antes porque nada, até o exec-based git
     desta task, escrevia de dentro do próprio container do agente (o checkpoint do driver
     Docker roda fora dele). Corrigido com um novo parâmetro `writable_files` (arquivo tocado
     vazio, não diretório, se ausente) — mas só para `.gitconfig`: os demais nomes
     (`.claude.json`, `.bashrc`, `.bash_profile`, `.bash_login`, `.profile`) **continuam** em
     `writable_paths` de propósito — a CLI os substitui pelo padrão temp-file-e-rename, que
     precisa de direito de criar/remover ENTRADA no diretório pai, só concedido por uma regra do
     Landlock no diretório, não no arquivo (achado ao vivo: movê-los pra `writable_files` quebrou
     a primeira chamada ao modelo tanto no driver Kubernetes quanto, confirmado em seguida, no
     Docker — regressão real, não específica de driver, revertida antes de prosseguir).
  3. Corrida real entre a run virar `succeeded` no banco e `record_checkpoint` terminar de
     verdade: no driver Docker cada chamada `git` é um subprocess local (rápido); no driver
     Kubernetes cada uma é um round-trip de exec via API (mais lento), tornando a corrida visível
     no teste — corrigido esperando o checkpoint aparecer antes de validar (sem mudança no
     código de produção, só no teste).

  Suite completa (unit + integration, Docker + Kubernetes + paridade + os dois E2E) roda limpa:
  384 unit, 49 integration, sem container Docker nem objeto Kubernetes órfão ao final.

## Workflow follow-up

- Atualizar `docs/roadmap-confinamento-do-agente.md` (etapa 8) para refletir o resultado real da
  validação em `kind` antes de considerar a etapa concluída.
- Arquivar esta change (`/opsx:archive`) depois da revisão, sincronizando as specs
  `container-driver-kubernetes` (nova) e `container-lifecycle` (modificada).
