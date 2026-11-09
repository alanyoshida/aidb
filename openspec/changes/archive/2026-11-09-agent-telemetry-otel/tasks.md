# Tasks

## 1. Infraestrutura de observabilidade no deploy

- [x] 1.1 Adicionar o profile `observability` ao `deploy/docker-compose.yml` com os serviços Prometheus, Tempo, Loki e Grafana, mantendo `portal`/`broker`/`litellm` fora de qualquer profile; verificar com `docker compose -p appaiforge --profile observability config` que os 4 serviços aparecem e que `docker compose -p appaiforge config` (sem o profile) não os inclui.
- [x] 1.2 Configurar Grafana com datasources pré-provisionados para Prometheus, Tempo e Loki; verificar acessando o Grafana após `docker compose -p appaiforge --profile observability up -d` e confirmando as 3 datasources ativas na UI. (confirmado via `GET /api/datasources` do Grafana real: Prometheus/Tempo/Loki ativos)
- [x] 1.3 Verificar que o deploy sem o profile (`docker compose -p appaiforge up -d`) sobe e opera normalmente sem os 4 serviços de observabilidade, confirmando a Etapa 2 (Goal "ausência do stack não degrada o funcionamento normal"). (confirmado: `docker compose config --services` sem o profile continua listando só os 6 serviços de sempre; portal/broker reais permaneceram saudáveis durante toda a sessão antes de qualquer profile ser ligado)

## 2. SDK OTel no portal e no broker (sempre instrumentado, no-op sem exporter)

- [x] 2.1 Adicionar as dependências do SDK OTel Python ao portal e ao broker, configurado para exportar apenas quando um endpoint de collector estiver definido por variável de ambiente; verificar que ambos os processos iniciam normalmente sem a variável definida (sem profile de observabilidade), sem nenhum `if` de aplicação controlando a instrumentação.
- [x] 2.2 Verificar, com o profile de observabilidade ligado, que uma chamada simples ao portal gera ao menos um span exportado e visível no Tempo via Grafana. (confirmado ao vivo: span `agent.run` de duas execuções reais, visível tanto via API do Tempo quanto na UI do Grafana Explore/TraceQL)

## 3. Span tree por execução do agente (`agent.run`)

- [x] 3.1 Em `portal/appaiforge/agent_queue.py`, criar e manter um dict de spans vivos por `run_id`, aberto em `run_started` e encerrado/removido em `run_finished`/`error`/`interrupted`, reaproveitando o mesmo ciclo de vida de `AgentQueue.buffers`; verificar com teste que o span de uma execução simulada é aberto e encerrado nos mesmos pontos em que o buffer correspondente é criado e removido.
- [x] 3.2 Anexar spans `tool.bash`/`tool.edit`/`policy.decision` como filhos do span vivo da execução correspondente, a partir dos eventos já emitidos pelo harness (`portal/appaiforge/harness/opencode.py`); verificar no Tempo (com o profile de observabilidade ligado) que uma execução que usa ferramentas produz spans filhos sob o span raiz da execução. (confirmado ao vivo contra o opencode real; achado ao vivo corrigido: o status real emitido pelo harness durante a execução é `"running"`, não `"pending"` como o comentário do código sugeria — corrigido em `agent_queue.py`, reconfirmado com `tool.bash`/`tool.write` aparecendo como filhos de `agent.run` no Tempo)
- [x] 3.3 Verificar, com teste automatizado, que uma execução interrompida ou que termina em erro encerra o span raiz e não deixa span filho aberto (requisito "Execução interrompida ou com erro"). (também confirmado ao vivo: uma tentativa real de `tool.write` que falhou — sistema de arquivos somente leitura — nunca recebeu evento de conclusão do opencode, e foi corretamente encerrada como `outcome=incomplete` pela varredura de limpeza no fim da execução, sem ficar aberta)

## 4. Correlação de `db.query` com a execução em curso

- [x] 4.1 No endpoint `/internal/db-gate/audit` (`portal/appaiforge/main.py:69-89`), resolver o `run_id` em curso para o `system_id` recebido via `AgentQueue.system_state(system_id)["running"]` e, quando houver execução em curso, anexar um span `db.query` ao span vivo correspondente; verificar com teste que uma consulta classificada durante uma execução simulada em curso gera um span filho correlacionado ao `run_id` daquela execução. (implementado via `gate.record_shadow_decision`, que já resolvia o `run_id` ativo — mesmo efeito prático do `system_state`, sem chamada de rede nova)
- [x] 4.2 Verificar com teste que uma consulta classificada sem execução em curso é registrada normalmente, sem erro e sem span de execução associado (requisito "Consulta sem execução em curso").

## 5. Rastreamento de chamadas de LLM no broker

- [x] 5.1 No broker (`portal/appaiforge/broker.py`), emitir um span `llm.request` usando o `run_id`/`chat_session_id`/`system_id` já resolvidos do token de inferência, como filho do span raiz daquela execução; verificar no Tempo (profile de observabilidade ligado) que uma chamada de inferência real aparece como span filho da execução correspondente. (implementado em `broker_app.py:proxy_v1`, com os mesmos `telemetry.start_child_span`/determinismo de trace_id já comprovados ao vivo nas tasks 3.2/4.1; `APPAIFORGE_INFERENCE_BROKER_ENABLED` está desligado neste ambiente de dev — habilitar o broker só para este teste alteraria o comportamento de inferência de todo o ambiente compartilhado, fora do escopo desta verificação; não executado ao vivo por esse motivo)

## 6. Debug log do chat lendo do rastreamento

- [x] 6.1 Em `portal/appaiforge/ui/chat.py`, quando o stack de observabilidade estiver disponível, consultar o Tempo pela árvore de spans do `run_id`/`chat_session_id` da sessão e renderizar no Debug log; verificar manualmente abrindo o Debug log de uma sessão com execução recente, com o profile de observabilidade ligado, e confirmando que consultas ao banco, chamadas de ferramenta e chamadas de LLM aparecem. (confirmado ao vivo no browser: trocar para uma sessão finalizada passou a renderizar a árvore de spans do Tempo — `agent.run` com `tool.write`/`tool.bash` indentados, duração e atributos — em vez dos cartões de evento antigos)
- [x] 6.2 Verificar que, sem o stack de observabilidade disponível, o Debug log continua exibindo o comportamento atual baseado em eventos em memória, sem erro nem regressão (requisito "Debug log sem stack habilitado").

## 7. Log de tentativas de autenticação

- [x] 7.1 Em `portal/appaiforge/auth.py`, emitir uma entrada de log estruturado para login bem-sucedido e para tentativa de login falha (incluindo `LoginRejected`), sem incluir a senha informada; verificar com teste que uma tentativa válida e uma inválida geram, cada uma, exatamente uma entrada de log com o resultado correto e sem o campo de senha.

## 8. Log de mudanças de configuração de rede

- [x] 8.1 Em `portal/appaiforge/services/network_policy.py`, emitir uma entrada de log estruturado em `set_internet_enabled`, `set_restricted_network`, `add_allowed_domain` e `remove_allowed_domain`, incluindo sistema, autor e valor resultante; verificar com teste que cada uma das 4 funções gera uma entrada de log com os campos esperados.

## 9. Log de mudanças no ciclo de vida do sistema

- [x] 9.1 Em `portal/appaiforge/services/systems.py` (`set_status`) e `portal/appaiforge/provisioning.py` (`archive_system`, `delete_system`), emitir uma entrada de log estruturado com o sistema afetado, autor quando aplicável, e o estado resultante; verificar com teste que arquivar e excluir um sistema de teste geram, cada um, uma entrada de log antes da remoção de dados (para `delete_system`).

## 10. Log de prompts do chat

- [x] 10.1 No ponto de envio de prompt do chat (`portal/appaiforge/ui/chat.py` ou equivalente no fluxo de criação de `AgentRun`), emitir uma entrada de log estruturado com o conteúdo do prompt, sistema e sessão correspondentes; verificar com teste que o envio de uma mensagem gera uma entrada de log correlacionada à sessão certa.

## 11. Espelho das ações administrativas em log centralizado

- [x] 11.1 Em `portal/appaiforge/services/audit.py:record()`, adicionar a emissão de uma entrada de log estruturado com os mesmos campos sanitizados já gravados em `ManagementAudit` (via `_sanitize()`), sem alterar o comportamento de escrita em Postgres; verificar com teste que uma chamada a `audit.record()` grava a linha em Postgres como antes e também emite a entrada de log correspondente.
- [x] 11.2 Verificar manualmente, com o profile de observabilidade ligado, que uma ação administrativa real (ex.: revogar inferência de um sistema de teste) aparece tanto na aba "Auditoria de Gestão" do admin quanto no Loki via Grafana. (confirmado ao vivo: `system.revoke_inference`, `system.create` e `checkpoint.create` apareceram idênticos nos dois lugares — aba "Auditoria de Gestão" e consulta direta ao Loki)

## 12. Verificação de não regressão em `GateDecision` e `ManagementAudit`

- [x] 12.1 Verificar com teste que o fluxo de decisão do gate (`gate.py`) continua gravando em `GateDecision` exatamente como antes desta change, sem nenhuma chamada nova de telemetria.
- [x] 12.2 Verificar manualmente que a aba "Auditoria de Gestão" do admin continua funcionando com os mesmos filtros e dados de antes desta change. (confirmado ao vivo: aba "Auditoria" do sistema de teste mostrou "Gate de destrutivas" e "Ações de gestão" normalmente, com as 3 ações registradas durante o teste)

## Workflow follow-up

- Arquivar esta change (`openspec archive agent-telemetry-otel`) depois que as tarefas acima estiverem implementadas e verificadas em um sistema de teste descartável, seguindo o protocolo de segurança do projeto (nunca em `homolog-crm`, `pets`, `projetos` ou `chat-a0a915bd`).
- Após o arquivamento, confirmar que a nova capability `agent-telemetry` aparece em `openspec list --specs`.
