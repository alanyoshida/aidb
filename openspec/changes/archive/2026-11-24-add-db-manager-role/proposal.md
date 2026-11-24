# Proposal

## Why

Hoje cada dono de sistema cadastra as próprias conexões de banco, com host, usuário e
senha. Isso espalha credenciais de banco por quem constrói sistemas, impede que a
mesma conexão sirva a mais de um sistema e deixa quem responde pelos bancos sem
controle sobre quem acessa o quê. A credencial de banco precisa de um responsável
central, e cada sistema deveria receber só o acesso que de fato usa.

Além disso, o gate de SQL recusa toda DDL em qualquer modo, então o agente não consegue
criar nem reestruturar tabelas no início da construção de um sistema.

## What Changes

- Nova capacidade **DB Manager**, acumulável ao tipo global do usuário (um `editor` pode
  ser também DB Manager). O admin continua podendo tudo. No modo `local` o admin concede
  a capacidade no cadastro do usuário; no modo `oidc` ela vem do papel `db_manager` no
  mesmo claim de papéis.
- **BREAKING**: as conexões de banco deixam de pertencer a um sistema e passam a formar
  um **catálogo único**, gerido por DB Managers e admins. O dono do sistema não cadastra,
  não edita e não remove mais conexões.
- Nova camada de **autorização por sistema**: o DB Manager autoriza uma conexão do
  catálogo para um sistema e define o **teto** de modo de acesso daquele sistema.
- Nova camada de **ativação**: o dono do sistema ativa ou não cada conexão autorizada,
  escolhendo o **alias** e um modo de acesso igual ou abaixo do teto. Agente (MCP), app
  gerada (`DATABASE_URL_<ALIAS>`) e manifesto de conexões só enxergam as conexões ativas.
- **BREAKING**: o dono do sistema passa a ver apenas nome, descrição, tipo, saúde, teto e
  modo ativo da conexão. Host, porta, banco e usuário ficam restritos a quem gere o
  catálogo.
- Novo modo de acesso **`schema_admin`**, acima de `read_write`: libera DDL e DML em
  massa **apenas para o agente**. A app gerada continua sem DDL em qualquer modo. O
  rebaixamento é manual, com um selo "DDL liberada desde <data>" visível ao dono e ao
  DB Manager.
- **Revogação imediata**: revogar a autorização, rebaixar o teto ou excluir a conexão do
  catálogo reaplica o provisionamento dos sistemas afetados na hora. O dono é avisado na
  aba de conexões do sistema, com data e autor, até dispensar o aviso.
- Conceder `schema_admin` numa conexão autorizada para outros sistemas, e excluir do
  catálogo uma conexão em uso, exigem confirmação com a lista dos sistemas afetados.
- BigQuery entra no catálogo com dois limites: não oferece `schema_admin`, e a revogação
  avisa o DB Manager de que a chave já entregue só é invalidada de vez ao ser rotacionada
  no GCP.
- **Migração**: cada conexão existente vira um item do catálogo já autorizado e ativo no
  sistema de origem, com o nome atual como alias e o modo atual como teto e modo ativo.
  Nenhuma app ou agente perde acesso no upgrade.
- Toda ação nova (cadastro no catálogo, autorização, revogação, mudança de teto,
  ativação, desativação e mudança de modo) entra na trilha de auditoria de gestão.

Fora do escopo: fluxo de solicitação de acesso dentro do portal (o dono combina com o
DB Manager por outro canal e não vê o catálogo), prazo de expiração para `schema_admin`,
e aplicar `read_only` no proxy para o bash do agente e para a app gerada (hoje vale só
para o MCP, e mudar isso quebraria apps existentes).

## Capabilities

### New Capabilities
- `db-connection-access`: autorização de conexões do catálogo por sistema, teto e modo de
  acesso, ativação pelo dono com alias, revogação imediata e avisos ao dono.

### Modified Capabilities
- `db-connections`: o cadastro passa a ser um catálogo gerido pelo DB Manager; provisão,
  variável de ambiente e remoção passam a depender de ativação e alias; saúde por conexão
  do catálogo; o que o dono enxerga é reduzido.
- `portal-identity`: nova capacidade de DB Manager, acumulável ao tipo global e concedida
  pelo admin no modo `local`.
- `oidc-authentication`: a capacidade de DB Manager vem do papel `db_manager` no token e
  acompanha a revalidação da sessão.
- `destructive-gate`: o agente deixa de ter DDL e DML em massa recusados quando a conexão
  está ativa em `schema_admin`; essas liberações são auditadas.
- `db-gate-proxy`: o listener de origem `agente` repassa statements bloqueadas e
  confirmáveis em conexões `schema_admin`; o listener da app não muda.
- `db-bigquery`: cadastro pelo DB Manager, variável de ambiente pelo alias, sem
  `schema_admin` e com aviso de rotação de chave na revogação.
- `management-audit`: a trilha passa a cobrir autorização, revogação, teto, ativação,
  desativação e mudança de modo.
- `system-git-remote`: o manifesto de conexões passa a listar alias e tipo das conexões
  ativas.
- `deploy-only-system`: a conferência do manifesto passa a exigir conexão ativa com o
  mesmo alias.

## Impact

- **Dados**: `db_connections` perde `system_id` e `access_mode`; nova tabela de
  autorizações por sistema e nova tabela de avisos; `users` e `sessions` ganham o
  indicador de DB Manager. Migração Alembic com transformação de dados.
- **Portal**: `models.py`, `rbac.py`, `auth.py`, `oidc.py`, `services/connections.py`,
  `services/directory.py`, `services/audit.py`, `provisioning.py`, `deploy.py`,
  `git_sync.py`, `ui/system_detail.py`, `ui/admin.py`, `ui/shell.py` e uma página nova
  para o catálogo.
- **Imagem base**: `dbproxy/sidecar.py`, `dbproxy/pg_proxy.py`, `dbproxy/mysql_proxy.py`
  e `gated-mcp/mcp_server.py` passam a conhecer o modo `schema_admin`.
- **IdP**: instalações `oidc` que queiram DB Managers precisam criar o papel `db_manager`.
- **Documentação**: guia de uso, segurança, autenticação e um ADR novo para o modelo de
  catálogo, autorização e ativação.
