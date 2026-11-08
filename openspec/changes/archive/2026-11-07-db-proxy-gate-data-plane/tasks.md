# Tasks

## 1. Spikes e bloqueios (fechar antes de codar o caminho crítico)

- [x] 1.1 Rodar o spike S8: proxy Python asyncio minimal contra Postgres real — startup + auth SCRAM-SHA-256 no upstream, simple query (`Q`) e extended (`P`/Parse) repassados, statement segurada e liberada sem corromper framing; registrar o comportamento observado
- [x] 1.2 Rodar o spike do MySQL: `COM_QUERY` + auth (`mysql_native_password`/`caching_sha2_password`) contra MySQL real; registrar se o enforcing desta etapa cobre MySQL ou se ele fica em sombra até a autenticação destravar (decisão prevista no design, riscos)

## 2. Proxy de wire protocol Postgres

- [x] 2.1 Implementar o framing do protocolo Postgres v3 (startup, autenticação do lado do servidor em loopback, autenticação com credencial real no upstream, repasse de mensagens) em módulo novo na base-image; testar com `psql` e `asyncpg` executando SELECT simples
- [x] 2.2 Classificar cada statement com o `sqlgate` canônico no `Q` e no `Parse`: `normal` repassa, `bloqueada` devolve `ErrorResponse` ao cliente sem tocar o banco; testar DROP recusado e DELETE por PK liberado
- [x] 2.3 Implementar a espera de aprovação para `confirmável`: segurar a statement, consultar o portal, liberar após aprovação ou devolver erro após recusa/timeout; testar os três desfechos
  - revisão (D8/ADR 0023, 2026-11-07): o hold foi substituído por recusa direta — ver tarefa 10.1

## 3. Proxy de wire protocol MySQL

- [x] 3.1 Implementar o framing e a classificação em `COM_QUERY` e `COM_STMT_PREPARE` com a mesma lógica do Postgres; testar com cliente `mysql` real
- [x] 3.2 Implementar a autenticação upstream MySQL (`mysql_native_password`, `caching_sha2_password`); testar conexão sem senha do cliente executando consulta

## 4. Decisão humana no portal

- [x] 4.1 Criar o endpoint interno do portal para o proxy registrar o pedido de aprovação (com token de serviço, padrão do broker) e consultar o resultado; testar pedido criado, aprovado, recusado e expirado
  - revisão (D8/ADR 0023, 2026-11-07): endpoint removido — nada mais cria pedido de aprovação, ver tarefa 10.1
- [x] 4.2 Associar o pedido ao run/sessão ativos do sistema (mesma atribuição do broker) e ligar à UI de aprovação do chat existente; testar aprovação pelo chat liberando a statement
  - revisão (D8/ADR 0023, 2026-11-07): card de aprovação removido do chat — a atribuição ao run ativo (`_active_run_id`) continua, agora só para a notificação de bloqueio (tarefa 10.1)
- [x] 4.3 Implementar timeout da espera com recusa segura e erro claro ao cliente; testar `psql` recebendo erro após o timeout, sem hang
  - revisão (D8/ADR 0023, 2026-11-07): sem objeto — não há mais espera para ter timeout; a recusa é imediata

## 5. Provisionamento do sidecar

- [x] 5.1 Criar o container do sidecar por sistema com `network_mode: container:<id>`, portas próprias por conexão e os segredos das conexões no env do sidecar (não do sistema); testar sidecar subindo junto do sistema
- [x] 5.2 Apontar `DATABASE_URL_<NOME>` e os argumentos do MCP server para os DSNs de loopback sem usuário nem senha; testar `docker exec <sys> env` e `/proc/<mcp>/cmdline` sem credencial
- [x] 5.3 Implementar os dois listeners por sistema (agente/MCP vs app) preenchendo `origin` no `GateDecision`; testar decisão de cada caminho com a origem correta
- [x] 5.4 Garantir que `refresh_connections` e a reconciliação recriam sidecar e sistema de forma idempotente; testar troca de credencial de conexão propagando ao sidecar

## 6. Modos e comparação (sombra)

- [x] 6.1 Adicionar `APPAIFORGE_DB_GATE_MODE` (default `shadow`) em `config.py` e nos compose; em sombra o proxy classifica e audita mas deixa tudo executar, com os globs de `permission.bash` e o `reply_gate` ainda ativos; testar que DELETE em massa executa e é auditada como confirmável
- [x] 6.2 ~~Rodar o período de comparação do spike S5~~ — revisão (D8/ADR 0023, 2026-11-07): sem objeto para `confirmável`. A pergunta original era "o proxy erra menos que os globs o suficiente pra confiar a decisão sozinho?" — deixou de fazer sentido quando `confirmável` parou de decidir sozinho e passou a recusar igual a DDL (zero decisão automática "liberar", só "recusar"). Continua válido observar `bloqueada`/DDL em modo sombra se algum sistema optar por esse período, mas não bloqueia mais nada nesta change.

## 7. Enforcing

- [x] 7.1 Com `APPAIFORGE_DB_GATE_MODE=enforce`, remover os globs de SQL de `permission.bash` do config do agente (condicional ao modo — revisão: `reply_gate` fica no `HarnessPort`, é mecanismo genérico de permissão não-SQL); testar que o gate continua funcionando sem o protocolo de permissão
- [x] 7.2 ~~Remover~~ — revisão: `gate.extract_sql` fica (alimenta a comparação S5 em modo sombra, task 6.2); em `enforce` já fica inerte pela mesma via condicional da 7.1 (sem `permission.asked` de bash, o branch que chama `extract_sql` nunca dispara) — não precisa de remoção física. Suíte segue verde (nada mudou no código).
- [x] 7.3 ~~Virar o default para `enforce` após o S5 mostrar falso-positivo aceitável~~ — revisão (2026-11-07): virado por pedido direto do operador (parar de perguntar no chat para execuções de banco, com notificação no lugar), sem esperar o período formal de comparação — `shadow` segue disponível por flag para quem quiser observar antes de confiar.

## 8. Testes de aceitação

- [x] 8.1 Integração: `psql -f arquivo.sql` com `DELETE FROM clientes` (o caso que hoje passa pelos globs) aguarda aprovação do editor e executa só após aprovação
  - revisão: `tests/integration/test_db_gate_proxy.py` — statement roda de dentro do container real via `asyncpg` contra o loopback do proxy (sem `psql` na imagem; o efeito é o mesmo). Um HTTP mínimo com a rota interna de auditoria substitui o portal completo (evita subir NiceGUI/sync do LiteLLM só para o sidecar ter quem chamar); a real credencial de teste (testcontainers) é alcançada pelo container via o gateway da rede Docker, não por "localhost" (relativo ao processo do pytest).
  - revisão (D8/ADR 0023, 2026-11-07): reescrito — a statement agora é recusada direto (sem aguardar aprovação); o teste cobre a recusa imediata e a auditoria `confirmavel/bloqueada`, ver tarefa 10.1
- [x] 8.2 Integração: modo sombra executa tudo e audita, sem bloquear nada
- [x] 8.3 Integração: statement confirmável vinda do listener da app registra `origin` da app, distinta da do agente
  - revisão (D8/ADR 0023, 2026-11-07): a statement é recusada direto (não mais segurada) — a distinção de `origin` na auditoria continua valendo, só o desfecho mudou
- [x] 8.4 Integração: ambiente e cmdline do container do sistema sem credencial de banco utilizável, e app gerada funcionando pelo proxy
- [x] 8.5 E2E no stack dedicado (8081) com harness fake cobrindo o novo caminho, sem apontar para o ambiente real
  - revisão: `tests/e2e/test_db_gate_e2e.py` — o harness fake não executa bash de verdade, então o "caminho novo" (SQL real pelo proxy) não dá pra disparar por mensagem de chat; o teste usa uma mensagem "DELETE SEM WHERE" só pra deixar a run em `awaiting_approval` (o que o proxy usa pra achar o run_id), e dispara a statement de verdade via `asyncpg` de dentro do container, direto na porta do sidecar. `db_gate_mode` é env var do processo do portal — a fixture `enforce_portal` recria só o serviço `portal` do compose E2E em enforce e devolve a sombra (default) no teardown. Achados corrigidos no caminho: `tests/e2e/conftest.py` não limpava `gate_requests` antes de `agent_runs` (FK travava o reset entre sessões) nem via os sidecars (`network_mode: container:<id>`, sem entrada própria em `Networks` — o filtro por rede do `docker ps` nunca os alcançava, acumulando órfãos a cada sessão).
  - revisão (D8/ADR 0023, 2026-11-07): reescrito — sem card de aprovação pra clicar; o teste verifica que a statement falha na hora e que a notificação de bloqueio (`gate_denied`) aparece no chat com a query, ver tarefa 10.1

## 9. Documentação e decisão

- [x] 9.1 Registrar o ADR 0021 (gate no data plane), com a interceptação no control plane como decisão substituída e referência ao ADR 0017
- [x] 9.2 Atualizar a linha da etapa 4 no `docs/roadmap-confinamento-do-agente.md` com o status e os artefatos entregues
- [x] 9.3 Documentar no `README.md` o sidecar, os modos sombra/enforcing e o rollout por flag

## 10. Revisão: confirmável deixa de pedir aprovação (achado ao vivo, ADR 0023)

- [x] 10.1 Em `enforce`, tratar `confirmável` igual a `bloqueada` nos dois proxies (recusa direta, sem hold, sem consulta ao portal); remover a infraestrutura de pedido pendente sem chamador (`GateRequest.create_request/get_request/decide_request/list_pending_for_run`, os 2 endpoints internos, o cliente HTTP de hold do proxy, o card "proxy de banco" no chat); estender a notificação de bloqueio no chat (`gate_denied`) para cobrir `confirmável` também, com o motivo da recusa; atualizar os testes afetados (proxy, unitários do portal, integração, E2E) e os docs (README, specs, ADR 0021 + novo ADR 0023)
  - Testado: 48 testes do proxy (`base-image/dbproxy`) + 295 unitários do portal passando; validado ao vivo no `homolog-crm` (`DELETE FROM dono` recusado na hora, auditado como `confirmavel/bloqueada`, sem nenhum pedido de aprovação criado)
  - Deploy: base image reconstruída, os 4 sidecars reais recriados e o portal real redeployado
