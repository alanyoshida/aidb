# Tasks

## 1. Modelo de dados e migração

- [x] 1.1 Rodar `impact` do GitNexus em `DbConnection`, `User` e `Session` e registrar chamadores e risco na descrição do PR; verificar que todo ponto que lê `DbConnection.system_id`, `DbConnection.name` ou `access_mode` está listado nas tasks dos grupos 3 a 7
- [x] 1.2 Atualizar `models.py` conforme D3: `users.db_manager`, `sessions.db_manager`, `DbConnection` sem `system_id`/`access_mode` e com `name` único, novos modelos `DbConnectionGrant` e `SystemConnectionNotice`; verificar com teste unitário que cria uma conexão, duas autorizações e um aviso e que as duas unicidades (par conexão/sistema e `alias_key` entre ativas) são recusadas pelo banco
- [x] 1.3 Escrever a migração Alembic com a transformação de dados do Migration Plan; verificar com teste que parte do schema anterior com dois sistemas, cada um com uma conexão `main` (uma delas `read_only`), e confere após o `upgrade`: duas conexões no catálogo com nomes distintos, autorizações ativas com alias `main` e teto e modo iguais ao `access_mode` anterior
- [x] 1.4 Implementar o `downgrade` conforme o plano de rollback; verificar com teste de ida e volta quando cada conexão tem uma autorização, e que o `downgrade` aborta com mensagem clara quando uma conexão está autorizada para dois sistemas
- [x] 1.5 Escrever o ADR do modelo de catálogo, autorização e ativação em `docs/adr/` (próximo número livre) e listá-lo em `docs/adr/README.md`; verificar que o link do índice abre o arquivo

## 2. Capacidade de DB Manager

- [x] 2.1 Adicionar `is_db_manager` a `Principal` e a `User`, preencher em `auth.resolve_principal()` (banco no modo `local`, snapshot da sessão no `oidc`) e criar `rbac.can_manage_catalog()` (D1), rodando `impact` antes de editar; verificar com testes em `tests/unit/test_rbac.py`: admin sem o indicador passa, editor com o indicador passa, editor e `app_user` sem ele não passam
- [x] 2.2 Adicionar ao serviço de diretório a concessão e a retirada da capacidade, restritas a admin e ao modo `local`, com auditoria; verificar em `tests/unit/test_directory_admin.py`: admin concede e retira, não-admin é recusado, modo `oidc` recusa, break-glass não é alterável
- [x] 2.3 Reconhecer o papel `db_manager` em `oidc.py` fora do rank de tipos, gravar o indicador no usuário-sombra e no snapshot da sessão e atualizá-lo na revalidação (D2); verificar em `tests/unit/test_oidc.py` os quatro cenários de "Capacidade de DB Manager vinda do token"
- [x] 2.4 Incluir a opção "DB Manager" no painel de usuários do admin (editável no modo `local`, coluna somente leitura no `oidc`); verificar com cenários BDD em `tests/bdd/test_portal_identity.py` para os dois requisitos novos de `portal-identity` e com o E2E `tests/e2e/test_admin_users.py`
- [x] 2.5 Criar o papel `db_manager` no realm de teste do Keycloak e documentar em `docs/autenticacao.md` como concedê-lo no IdP; verificar com um cenário em `tests/e2e_oidc/test_oidc_flows.py` em que um usuário com `editor` e `db_manager` abre o catálogo

## 3. Catálogo de conexões

- [x] 3.1 Reescrever cadastro, edição e exclusão em `services/connections.py` para o catálogo, guardados por `can_manage_catalog`: nome único, tipo imutável, novo teste de conexão quando endereço ou credencial mudam, rodando `impact` antes de editar; verificar em `tests/unit/test_connections.py` os cenários de "Catálogo de conexões gerido pelo DB Manager", "Edição de conexão do catálogo" e "Teste de conexão antes de salvar"
- [x] 3.2 Separar as duas projeções seguras da conexão: a de quem gere o catálogo (com host, porta, banco, usuário) e a do dono do sistema (nome, descrição, tipo, saúde); verificar com teste que a projeção do dono não contém host, porta, banco, usuário nem service account email, para os três tipos
- [x] 3.3 Fazer a checagem periódica de saúde percorrer o catálogo, uma vez por conexão, e o resumo de degradadas listar os sistemas autorizados (D11); verificar com teste que uma conexão autorizada para dois sistemas é checada uma vez por ciclo e que uma conexão sem autorização também é checada
- [x] 3.4 Registrar `conn.create`, `conn.update` e `conn.delete` na auditoria sem dados de endereço nem segredos (D12); verificar em `tests/unit/test_management_audit.py`

## 4. Autorização e ativação

- [x] 4.1 Implementar autorizar, revogar e alterar teto, com teto padrão `read_write`, recusa de autorização duplicada e limite `read_write` para BigQuery, mais a listagem de sistemas com nome, slug e dono para a escolha; verificar com testes unitários dos cenários de "Autorização de conexão por sistema", "Teto de modo de acesso por autorização", "Sistemas visíveis ao autorizar" e "Modos de acesso disponíveis para BigQuery"
- [x] 4.2 Implementar ativar, desativar e mudar modo para quem gerencia o sistema, com validação do alias, unicidade por `alias_key` entre ativas, alias imutável enquanto ativa e limite pelo teto (D4, D5); verificar com testes unitários dos cenários de "Ativação pelo dono do sistema", "Alias definido na ativação" e "Modo de acesso ativo limitado ao teto"
- [x] 4.3 Reduzir o modo vigente quando o teto é rebaixado, manter `schema_admin_since` e expor os outros sistemas autorizados para a confirmação de `schema_admin`; verificar com testes unitários dos cenários de "Rebaixamento de teto com efeito imediato", "Indicação de DDL liberada" e "Confirmação ao conceder schema_admin em conexão compartilhada"
- [x] 4.4 Implementar os avisos ao dono (criação só quando a ação muda o que o sistema recebe, listagem e dispensa por quem gerencia o sistema) conforme D9; verificar com testes unitários dos cenários de "Aviso ao dono sobre revogação e rebaixamento"
- [x] 4.5 Fazer a exclusão do catálogo revogar todas as autorizações e gerar os avisos, e devolver o indicador de rotação de chave para BigQuery; verificar com testes unitários dos cenários de "Exclusão de conexão do catálogo" e "Aviso de rotação de chave ao revogar BigQuery"
- [x] 4.6 Registrar `conn.grant`, `conn.revoke`, `conn.ceiling`, `conn.activate`, `conn.deactivate` e `conn.mode` na auditoria, com o sistema relacionado; verificar em `tests/unit/test_management_audit.py` os cenários novos de `management-audit`
- [x] 4.7 Escrever a feature BDD da capability `db-connection-access` em `tests/bdd/` cobrindo autorizar, ativar com alias, modo acima do teto recusado e revogação; verificar que os cenários passam com `uv run pytest tests/bdd`

## 5. Provisionamento pelo alias

- [x] 5.1 Criar o leitor único de conexões vigentes de um sistema (D6) e trocar por ele as leituras de `provisioning.py` (manifesto do sidecar com o modo, `DATABASE_URL_<ALIAS>`, config do opencode, config do Claude Code), rodando `impact` antes de editar; verificar atualizando `tests/unit/test_provisioning_driver.py`, `test_claude_code_provisioning.py` e `test_llm_provisioning.py` e com um teste novo em que a mesma conexão tem aliases diferentes em dois sistemas e uma conexão autorizada e inativa não aparece em nenhum artefato
- [x] 5.2 Trocar a conferência de manifesto de `deploy.py` para os aliases das conexões ativas; verificar em `tests/unit/test_deploy_rules.py` e nos cenários BDD de "Conexões exigidas pela versão", incluindo o de conexão autorizada e não ativada
- [x] 5.3 Trocar o manifesto de conexões de `git_sync.py` para alias e tipo das conexões ativas; verificar nos cenários BDD de "Manifesto de conexões gravado a cada checkpoint", incluindo o de conexão não ativada
- [x] 5.4 Ligar o reprovisionamento às ações conforme D7, com execução em sequência e fora do request quando vários sistemas são afetados; verificar com teste usando o driver fake que revogar, desativar, mudar modo e editar credencial reprovisionam exatamente os sistemas com autorização ativa, e que autorizar, renomear no catálogo e rebaixar teto sem reduzir o modo não reprovisionam

## 6. Proxy e MCP: schema_admin

- [x] 6.1 Fazer `base-image/dbproxy/sidecar.py` ler o modo de cada conexão do manifesto e habilitar o repasse de statements destrutivas só no listener de origem `agente`, tratando modo ausente como `read_write` (D8); verificar em `base-image/dbproxy/test_sidecar.py`
- [x] 6.2 Implementar o repasse em `pg_proxy.py` e `mysql_proxy.py` quando habilitado e o gate está em `enforce`; verificar em `test_pg_proxy.py` e `test_mysql_proxy.py`: `DROP` e `DELETE` em massa passam no listener do agente em `schema_admin`, são recusados no listener da app e são recusados nos dois quando o modo é `read_write`
- [x] 6.3 Auditar no portal as statements liberadas com uma decisão própria e exibi-la no histórico do gate da página do sistema; verificar em `base-image/dbproxy/test_portal_gate.py` e num teste unitário do portal do cenário "DDL liberada fica no histórico"
- [x] 6.4 Aceitar `schema_admin` em `base-image/gated-mcp/mcp_server.py` mantendo as ferramentas só de leitura, e incluir o modo vigente no rótulo da ferramenta gerado pelo provisionamento; verificar em `base-image/gated-mcp/test_mcp_access_mode.py` e nos cenários de "Contexto da conexão exposto ao agente"
- [x] 6.5 Reconstruir a imagem base e cobrir o caminho completo em `tests/e2e/test_db_gate_e2e.py`: com a conexão em `schema_admin` o agente executa `DROP TABLE` e a app tem a mesma statement recusada, e depois do rebaixamento o agente volta a ser recusado; verificar que o teste passa contra o stack E2E
- [x] 6.6 Documentar em `docs/seguranca.md` o modo `schema_admin`, o fato de valer só para o agente, o efeito do gate em modo sombra e a limitação de que `read_only` só é aplicado no MCP; verificar que os exemplos citados correspondem ao comportamento dos testes de 6.2

## 7. Interface

- [x] 7.1 Carregar a skill `impeccable` e criar a página "Bancos de dados" com o catálogo (criar, editar, testar, excluir com confirmação e lista de sistemas afetados), acessível pelo menu só a DB Managers e admins, seguindo `DESIGN.md`; verificar com teste E2E em que um DB Manager cadastra e edita uma conexão e um editor sem a capacidade não vê o item de menu e tem o acesso direto recusado
- [x] 7.2 Adicionar à página as autorizações de cada conexão: escolha do sistema por nome, slug e dono, teto, revogação com confirmação, confirmação de `schema_admin` em conexão compartilhada, selo de DDL liberada e aviso de rotação de chave para BigQuery; verificar com teste E2E dos fluxos de autorizar, elevar teto e revogar
- [x] 7.3 Mover o painel de conexões degradadas de `ui/admin.py` para a página nova, com os sistemas autorizados de cada conexão; verificar que o admin e o DB Manager veem o resumo na página nova e que o painel antigo não existe mais
- [x] 7.4 Refazer a aba "Conexões" de `ui/system_detail.py`: lista das conexões autorizadas com os dados permitidos ao dono, ativar (alias e modo), desativar, mudar modo, selo de DDL liberada e avisos com dispensa, removendo os formulários de cadastro e edição; verificar com teste E2E que o dono ativa uma conexão com alias próprio, não vê host nem usuário e dispensa um aviso de revogação
- [x] 7.5 Atualizar os fluxos E2E existentes que cadastravam conexão pela página do sistema (`tests/e2e/test_systems.py`, `test_full_journey.py`, `tests/e2e_gitlab/test_deploy_only.py` e as fixtures de `tests/e2e/conftest.py`) para o caminho catálogo, autorização e ativação; verificar que as três suítes E2E passam
- [x] 7.6 Atualizar `docs/guia-de-uso.md` com o papel de DB Manager, o catálogo, a autorização, a ativação com alias, os modos de acesso e o que acontece numa revogação, e `README.md` onde descreve o cadastro de conexões; verificar que cada passo descrito corresponde a um fluxo coberto nos testes E2E de 7.1 a 7.4

## 8. Verificação integrada

- [x] 8.1 Rodar `uv run pytest -n 8 tests/unit tests/bdd`, `uv run pytest tests/integration` e os testes de `base-image/`; verificar que tudo passa
- [x] 8.2 Rodar as suítes `tests/e2e`, `tests/e2e_oidc` e `tests/e2e_gitlab`, uma de cada vez, contra seus stacks; verificar que tudo passa
- [x] 8.3 Subir um stack com a base no schema anterior e conexões cadastradas, aplicar a migração e confirmar no portal que agente e app de um sistema existente continuam com as mesmas conexões e variáveis de ambiente; verificar comparando o ambiente do container antes e depois
- [x] 8.4 Rodar `openspec validate add-db-manager-role --strict` e `detect_changes` do GitNexus com `scope: all`; verificar que a validação passa e que o resultado do `detect_changes` não é parcial nem truncado

## Workflow follow-up

- Arquivar a change antes de abrir o PR, conforme o fluxo do projeto (propose, apply, archive, PR, merge, release).
- Abrir o PR com o resultado do `impact` de 1.1 na descrição.
