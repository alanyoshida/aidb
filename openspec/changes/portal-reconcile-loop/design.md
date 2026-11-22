# Design

## Context

Ver proposal.md (Why). Estado atual relevante:

- `provisioning.reconcile()` percorre todos os sistemas, pula `archived` e `provisioning`, e para cada um chama `driver.reconcile_one()`. Quando a unidade principal não existe (ou, no Kubernetes, o Pod não tem o container `git` ou tem spec divergente), `reconcile_one` levanta `ComputeUnitNotFound` e `reconcile()` chama `provision_system()` e `publish_app_by_slug()`. Num portal de produção, sistema com agente é removido e fica em erro. No fim, checa a saúde das conexões de banco do sistema.
- A lista de sistemas é lida uma vez no começo da passada; o estado não é relido antes de agir. Uma exceção que não seja `ComputeUnitNotFound` nem `ComputeUnitOwnedElsewhere` (por exemplo `ApiException` 500 do cluster ou `docker.errors.APIError`) sobe e aborta a passada inteira.
- Outras operações recriam ou removem a unidade de um sistema fora de qualquer coordenação: `start_provisioning_thread` (estado `provisioning`), `refresh_connections` e `_reprovision_async` (troca de provedor), `refresh_https_allowlist` (no Docker recria só o sidecar; no Kubernetes recria o Pod inteiro), `archive_system` e `delete_system`. Só a primeira marca o sistema como `provisioning`.
- O portal já tem três laços de fundo, iniciados em `create_app()`: `health_monitor.start_monitor` (thread daemon, `while True` + `sleep`), `deploy.start_poller` (thread daemon com `threading.Event.wait`) e `telemetry.start_span_cleanup_timer` (`nicegui.app.timer`, async).
- O provisionamento pode demorar: no Kubernetes, `provision()` espera o container `agent` iniciar (até 30 s por Pod), e uma imagem nova precisa ser baixada.
- Uma réplica do portal só (chart `replicaCount: 1`; compose com um serviço `portal`).

## Goals / Non-Goals

**Goals:**
- Reconciliação de fato rodando na subida e periodicamente, nos dois drivers.
- Não disputar as operações do portal com o mesmo sistema nem ressuscitar sistema arquivado.
- Uma falha num sistema não derruba a passada nem o laço.

**Non-Goals:**
- Coordenação entre várias réplicas do portal (trava em banco, eleição de líder).
- Recuperar sistemas presos em `provisioning` por um reinício no meio do provisionamento.
- Mudar o que `reconcile_one` de cada driver considera divergência.

## Decisions

### D1. Laço em thread daemon, primeira passada imediata, fora do caminho da subida

`provisioning.start_reconcile_loop(interval=None, stop=None) -> threading.Thread`, no mesmo formato de `deploy.start_poller`: uma thread daemon que faz uma passada logo ao começar e depois espera `stop.wait(interval)` entre passadas. `create_app()` a inicia junto dos outros laços (depois de `register_pages()`/`write_portal_router()`, ao lado de `start_monitor()` e `start_poller()`).

- *Por que não síncrona em `create_app()`*: a passada da subida pode recriar vários Pods (30 s cada, mais o pull de imagem). Bloquear a subida atrasaria o `/api/health` e, no Kubernetes, poderia fazer a probe do Deployment matar o portal antes de ele subir, em laço.
- *Por que não `nicegui.app.timer`*: o timer roda no event loop; `reconcile()` faz chamadas bloqueantes ao Docker, ao cluster e aos bancos das conexões e congelaria a UI. O timer de spans aguenta isso porque é um `DELETE` a cada 6 h.
- A thread roda `reconcile()` dentro de `try/except Exception` com log: uma passada que falha não encerra o laço.

### D2. Intervalo configurável, padrão 300 s, `0` desliga só a periódica

`Settings.reconcile_interval: float = 300.0` (`APPAIFORGE_RECONCILE_INTERVAL`). Com valor `<= 0` a thread faz só a passada da subida e termina.

- 300 s: a saúde da app já é sondada a cada 15 s pelo `health_monitor`; a reconciliação é mais pesada (abre conexão com cada banco cadastrado, consulta cada unidade) e o que ela corrige — unidade removida por fora — não é urgente ao ponto de segundos. Também limita a frequência das tentativas de recriar um sistema que falha sempre (ver Riscos).
- No chart não há valor dedicado; o operador usa `portal.extraEnv`. Evita mais uma chave para um ajuste raro.

### D3. Trava por sistema, compartilhada com as operações que criam ou removem a unidade

`provisioning.system_operation_lock(system_id) -> threading.RLock` (dicionário de travas protegido por uma trava global, como `git_sync.system_lock`). Quem segura:

- `provision_system()` (cobre `start_provisioning_thread`, `refresh_connections`, `_reprovision_async` e o `refresh_https_allowlist` do Kubernetes, que chama `provision_system`);
- `refresh_https_allowlist()` (o do Docker recria o sidecar que `reconcile_one` também recria);
- `archive_system()` e `delete_system()`, em volta de remover a unidade e mudar o estado.

`reconcile()` tenta a trava de cada sistema **sem bloquear**; se está ocupada, pula o sistema nesta passada (com log em nível debug) e segue. Com a trava, relê o sistema do banco e pula se ele sumiu, está `archived` ou `provisioning`; só então chama `reconcile_one`/recriação. `RLock` porque a reconciliação segura a trava e chama `provision_system`, que a pega de novo.

- *Alternativa: marcar `provisioning` durante todo reprovisionamento.* Muda estado visível na UI em quatro caminhos e ainda deixa arquivamento/exclusão sem coordenação.
- *Alternativa: trava em banco (`SELECT … FOR UPDATE` / advisory lock).* Só se paga com várias réplicas (Non-Goal) e prenderia uma conexão do pool durante um provisionamento de dezenas de segundos.
- Arquivar e excluir esperam a trava (bloqueante): se a reconciliação estiver recriando aquele sistema, o arquivamento espera ela terminar e então remove o que foi criado. É o raro caso de contenção e o resultado fica correto.
- `git_sync.system_lock` não é reusado: protege operações git longas (checkpoint, sincronização) que não conflitam com recriar a unidade; juntar as duas faria a reconciliação pular sistemas durante cada checkpoint, e arquivar esperar um push.

### D4. Isolamento de falhas por sistema

Dentro do laço de `reconcile()`, cada sistema roda num `try/except Exception`: erro inesperado vira `log.exception` e o estado do sistema não muda (uma API do cluster fora do ar por um minuto não pode marcar todos os sistemas em erro). Os ramos que já existem continuam iguais: `ComputeUnitOwnedElsewhere` deixa em erro com o motivo; falha ao recriar deixa em erro com "reconciliação falhou: …". `_check_connections_health` continua rodando para o sistema mesmo quando a consulta da unidade falhou (já é isolada por conexão).

### D5. Recriação bem-sucedida volta o sistema a ativo

Depois de `provision_system()` e `publish_app_by_slug()` com sucesso no ramo `ComputeUnitNotFound`, `set_status(system_id, active, "")` — o mesmo que `start_provisioning_thread` faz ao terminar. Sem isso, a tentativa periódica conserta o container mas o sistema continua mostrando "reconciliação falhou" para sempre. Se a app não responder depois, o `health_monitor` volta a marcar "app fora do ar" como hoje. O ramo de portal de produção com agente e o de dono diferente não mudam.

### D6. Escrita de rota Docker idempotente

`edge._write()` compara o YAML que vai escrever com o conteúdo atual do arquivo e não reescreve quando é igual. A cada passada, a reconciliação chama `publish_app` para todo sistema não arquivado; sem isso, o file provider do Traefik recarregaria a configuração dinâmica a cada 5 minutos por sistema. No Kubernetes, `publish` faz `replace` dos objetos, que o API server não propaga quando o objeto não muda de fato — nada a fazer lá.

### D7. `republish_routes()` fica redundante

A change `gateway-api-traefik-subchart` (em andamento em outro branch) chama `provisioning.republish_routes()` na subida, sob o driver Kubernetes, para que uma troca de `k8s_routing_mode` valha para os sistemas existentes. A primeira passada da reconciliação chama `publish_app` para todo sistema não arquivado e não em provisionamento — um conjunto que contém o de `republish_routes` (só ativos) — e nos dois drivers. As diferenças: a reconciliação roda em segundo plano (as rotas migram segundos depois da subida, não antes do primeiro pedido) e não publica a rota de um sistema cuja consulta da unidade falhou por erro inesperado (`republish_routes` também não, porque o `publish` falharia pelo mesmo motivo). Nenhuma das duas justifica manter as duas chamadas.

Decisão: esta change não toca em `republish_routes` (não existe neste branch). Na integração das duas, remover a chamada da subida em `main.py` e a função, e trocar o teste unitário dela por um que verifique que a reconciliação publica a rota de sistemas em `active` e em `error`. O que fizer o merge por último faz isso; a nota fica registrada nas notas compartilhadas das sessões e no PR.

## Risks / Trade-offs

- [Pod recriado no meio de uma execução do agente] → só acontece se o Pod divergir da configuração, o que só muda com reinício do portal (env); na subida, `reconcile_orphaned_runs()` já encerrou as execuções órfãs. Comportamento já documentado em `docs/configuracao.md`.
- [Sistema que falha sempre ao recriar é tentado de novo a cada passada] → uma tentativa a cada 5 minutos por padrão, com o motivo visível no sistema; o operador arquiva o sistema ou aumenta o intervalo. Aceito: é a tentativa automática que a spec pede.
- [Sistema em erro "app fora do ar" é recriado se a unidade sumiu] → desejado: é o caso em que o container caiu e não voltou.
- [Arquivar espera uma recriação em andamento] → só quando a reconciliação está recriando aquele mesmo sistema; o arquivamento termina depois, com resultado correto.
- [Várias réplicas do portal reconciliando ao mesmo tempo] → fora do escopo; o chart e o compose sobem uma réplica. Documentado na docstring de `start_reconcile_loop`.
- [Checagem de saúde das conexões a cada passada abre uma conexão com cada banco cadastrado] → uma por conexão a cada 5 minutos; mesmo custo que a spec de conexões já previa para a reconciliação.

## Migration Plan

Nada a migrar. Ao atualizar, a primeira passada recria o que estiver faltando ou divergente — inclusive Pods antigos sem o container `git` ou com imagem velha, que antes esperavam um reprovisionamento manual. Para voltar ao comportamento anterior sem reverter o código não há chave (a passada da subida sempre roda); `APPAIFORGE_RECONCILE_INTERVAL=0` desliga a periódica.
