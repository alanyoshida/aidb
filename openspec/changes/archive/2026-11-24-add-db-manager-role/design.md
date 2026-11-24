# Design

## Context

Motivação e escopo estão em `proposal.md`. O que molda a solução no código atual:

- `DbConnection` tem `system_id` e nome único por sistema. Seis pontos leem conexões por
  `DbConnection.system_id == system.id`: manifesto do sidecar, `DATABASE_URL_*`, config do
  opencode, config do Claude Code, checagem de saúde (todos em `provisioning.py`),
  conferência de manifesto em `deploy.py` e manifesto de conexões em `git_sync.py`.
- O **nome** da conexão é contrato: vira `DATABASE_URL_<NOME>` (via `_env_name`), nome da
  ferramenta MCP, `connection_name` nas decisões do gate e entrada do manifesto no git.
- Variáveis de ambiente, manifesto do sidecar e config do agente são **fixados na criação
  do container**. Qualquer mudança de conexão hoje passa por `refresh_connections`, que
  recria o container e reinicia as sessões de chat.
- O tipo de usuário é um enum único com ordem linear no OIDC (`_ROLE_RANK`). No modo
  `oidc` o tipo e os grupos ficam num snapshot na sessão, revalidado a cada 5 minutos.
- O proxy de banco (`base-image/dbproxy`) não conhece `access_mode`. `read_only` é
  aplicado só no MCP (`gated-mcp/mcp_server.py`). DDL e DML em massa são recusados no
  proxy para as duas origens quando o gate está em `enforce`; em `shadow` nada é recusado.
- BigQuery não passa pelo proxy: MCP e app recebem a credencial real.

## Goals / Non-Goals

**Goals:**
- Um único caminho de leitura das conexões vigentes de um sistema, usado por todos os
  pontos de provisionamento.
- Nenhuma mudança de comportamento para sistemas existentes logo após a migração.
- Liberar DDL para o agente sem tocar o caminho da app gerada.

**Non-Goals:**
- Recarregar o sidecar a quente. A revogação usa o mesmo mecanismo de recriação de
  container que a remoção de conexão usa hoje.
- Aplicar `read_only` no proxy. O teto `read_only` continua valendo só para o MCP, como
  hoje; o bash do agente e a app não são barrados. Fechar isso quebraria apps existentes
  e fica para uma change própria.
- Dar ao DB Manager qualquer acesso a sistemas alheios além de nome, slug e dono.

## Decisions

### D1. DB Manager é um indicador, não um quarto tipo

`users.db_manager` (booleano) guarda a capacidade; `Principal` e `User` expõem
`is_db_manager`. `rbac.can_manage_catalog(user)` devolve verdadeiro para admin ou DB
Manager e é a única guarda do catálogo e das autorizações. O break-glass já é admin.

Alternativa descartada: um valor `db_manager` no enum `UserType`. O enum é exclusivo e
ordenado, e DB Manager não está acima nem abaixo de `editor`; além disso impediria um
editor de acumular a função.

### D2. OIDC: papel `db_manager` no mesmo claim, fora do rank

`oidc.py` reconhece `db_manager` no claim de papéis já configurado, sem incluí-lo em
`_ROLE_RANK`. O tipo continua vindo de `admin`/`editor`/`app_user`; um token só com
`db_manager` é recusado como hoje (nenhum tipo reconhecido). O indicador vai para o
snapshot da sessão (`sessions.db_manager`) e para o usuário-sombra, e é atualizado na
revalidação junto com tipo e grupos.

Alternativas descartadas: claim separado ou grupo do IdP (configuração nova de
instalação sem ganho).

### D3. Modelo de dados

```
db_connections (catálogo)          db_connection_grants (autorização)
  id                                 id
  name            único              connection_id  -> db_connections
  kind            imutável           system_id      -> systems
  host, port, database, username     max_mode       teto
  password_encrypted                 active         bool
  description                        alias          definido na ativação
  status, status_checked_at          alias_key      alias normalizado (_env_name)
  created_at                         mode           modo ativo (<= teto)
                                     schema_admin_since
                                     granted_by_email, created_at
                                     UNIQUE (connection_id, system_id)
                                     UNIQUE (system_id, alias_key) WHERE active

system_connection_notices
  id, system_id, kind (revoked | ceiling_lowered | connection_deleted),
  connection_name, alias, detail, actor_email, created_at, dismissed_at
```

`db_connections` perde `system_id` e `access_mode`. O `kind` passa a ser imutável depois
da criação, porque trocar o tipo de uma conexão compartilhada quebraria todos os
sistemas que a usam.

Os avisos ficam em tabela própria porque a autorização é apagada na revogação e a
conexão pode ser apagada do catálogo; o aviso guarda o nome e o alias como texto.

Alternativa descartada: manter `system_id` e copiar a conexão para cada sistema. Mantém
a credencial duplicada e a rotação de senha vira N edições.

### D4. Alias

O alias é texto livre validado (letras, dígitos, `_` e `-`), guardado junto de
`alias_key = _env_name(alias)`. A unicidade por sistema é sobre `alias_key` e só entre
autorizações ativas, porque `a-b` e `a_b` gerariam a mesma variável de ambiente. O alias
não muda enquanto `active`; na desativação ele é preservado na linha para pré-preencher
uma reativação, que pode escolher outro.

### D5. Modos e teto

Os modos são ordenados: `read_only` < `read_write` < `schema_admin`. O serviço recusa
ativar ou mudar para um modo acima de `max_mode`. Rebaixar `max_mode` abaixo do `mode`
vigente reduz `mode` para o novo teto na mesma transação. `schema_admin_since` é gravado
quando `mode` passa a `schema_admin` e limpo quando deixa de ser. Conexões BigQuery
aceitam `max_mode` de no máximo `read_write`.

### D6. Um único leitor de conexões vigentes

Uma função em `services/connections.py` devolve, para um sistema, as autorizações ativas
com a conexão do catálogo, o alias e o modo. Os seis pontos listados em Context passam a
usá-la, e tudo o que hoje usa `conn.name` como contrato passa a usar o **alias**:
variável de ambiente, nome da ferramenta MCP, entrada do manifesto do sidecar,
`connection_name` da decisão do gate, manifesto no git e conferência no deploy. O nome
do catálogo e os dados de host nunca chegam à página do sistema.

A descrição do catálogo continua indo para o rótulo da ferramenta MCP, como hoje.

### D7. "Imediato" significa reprovisionar na hora

Revogar, rebaixar teto que reduza o modo vigente, ativar, desativar e mudar o modo
disparam `refresh_connections` do sistema, exatamente como cadastrar ou remover conexão
faz hoje. Operações do catálogo que afetam vários sistemas (editar host ou credencial,
excluir a conexão) disparam o reprovisionamento de cada sistema com autorização ativa,
em sequência, fora do request. Mudanças que não alteram o que o container recebe
(autorizar, rebaixar teto sem reduzir o modo vigente, renomear no catálogo) não
reprovisionam.

Alternativa descartada: recarga a quente do sidecar. Cortaria Postgres e MySQL sem
recriar o container, mas o sidecar lê o manifesto do ambiente na partida, e BigQuery
exigiria recriação de qualquer forma.

### D8. `schema_admin` no proxy, só no listener do agente

Cada entrada do manifesto do sidecar ganha o modo ativo. O sidecar passa ao listener de
origem `agente` a permissão de repassar statements `bloqueada` e `confirmável` quando o
modo é `schema_admin`; o listener de origem `app` nunca recebe essa permissão. Com o gate
em `enforce`, o proxy repassa essas statements e as audita no portal com uma decisão
própria ("liberada por schema_admin"), para que o histórico do gate mostre toda DDL
executada. Em `shadow` nada muda.

O MCP continua sendo ferramenta de leitura; ele recebe o modo só para compor o rótulo,
de modo que o agente saiba que pode executar DDL pelo bash. A camada de dados da app
gerada (`app_template/dbgate.py`) não muda.

Alternativa descartada: liberar DDL por uma ferramenta MCP nova. O agente já usa bash e
`psql` para escrita, e o proxy é o ponto que vê todos os caminhos.

### D9. Avisos ao dono

Um aviso é criado quando a ação do DB Manager muda o que um sistema recebe: revogação de
autorização ativa, rebaixamento de teto que reduz o modo vigente e exclusão do catálogo
de conexão ativa no sistema. A aba de conexões do sistema lista os avisos não
dispensados; quem gerencia o sistema dispensa.

### D10. Interface

- Página nova "Bancos de dados", no menu de quem é DB Manager ou admin: catálogo
  (criar, editar, testar, excluir), autorizações de cada conexão (sistema por nome, slug
  e dono; teto; selo de DDL) e a lista de conexões degradadas, que sai do painel do admin
  e passa a viver aqui.
- Aba "Conexões" do sistema: lista as conexões autorizadas com nome, descrição, tipo,
  saúde, teto, estado e, quando ativas, alias e modo. Ações de quem gerencia o sistema:
  ativar (alias e modo), desativar, mudar modo, dispensar aviso. Os formulários de
  cadastro e edição de conexão saem da página.
- Painel de usuários do admin: opção "DB Manager" no modo `local`; coluna somente
  leitura no modo `oidc`.

Para autorizar, o DB Manager escolhe o sistema numa lista de todos os sistemas com nome,
slug e e-mail do dono. `visible_system_ids` e `can_access_system` não mudam.

### D11. Saúde por conexão do catálogo

A checagem periódica passa a percorrer o catálogo inteiro, uma vez por conexão,
inclusive as ainda não autorizadas, para que o DB Manager veja o estado antes de
autorizar.

### D12. Auditoria

Ações novas em `management_audit`: `conn.create`, `conn.update` e `conn.delete` (sem
sistema), `conn.grant`, `conn.revoke`, `conn.ceiling`, `conn.activate`,
`conn.deactivate` e `conn.mode` (com sistema). Os detalhes levam nome do catálogo, alias
e modos, nunca host, usuário ou senha.

## Risks / Trade-offs

- [Revogar ou rebaixar recria o container e reinicia as sessões de chat do sistema] → a
  confirmação da ação lista os sistemas afetados; o dono vê o aviso com data e autor.
- [O teto `read_only` só vale no MCP; bash do agente e app ainda escrevem] → limitação já
  existente, registrada em `docs/seguranca.md`; isolamento real de leitura exige um
  usuário de banco somente-leitura cadastrado como outra conexão.
- [`schema_admin` esquecido ligado] → selo com a data nos dois lados e registro de toda
  DDL no histórico do gate.
- [DDL de um sistema quebra outro que usa o mesmo banco] → confirmação listando os outros
  sistemas autorizados ao conceder `schema_admin`.
- [Gate em `shadow` torna `schema_admin` indistinguível de `read_write`] → comportamento
  já existente do modo sombra; documentado.
- [Chave BigQuery já lida pela app continua válida após a revogação] → aviso ao DB
  Manager pedindo a rotação da chave no GCP.
- [Editar a credencial de uma conexão muito compartilhada recria vários containers] →
  reprovisionamento em sequência, fora do request, com a lista de sistemas na confirmação.
- [Um editor que também é DB Manager autoriza bancos para os próprios sistemas] → aceito
  por decisão de produto; toda autorização é auditada com autor.
- [O dono não vê mais host nem usuário e perde contexto para diagnosticar] → tipo e saúde
  continuam visíveis; o diagnóstico de conectividade passa ao DB Manager.

## Migration Plan

1. Migração Alembic, numa transação:
   - cria `db_connection_grants` e `system_connection_notices`; adiciona
     `users.db_manager` e `sessions.db_manager`;
   - para cada conexão existente, cria a autorização do sistema de origem com
     `active = true`, `alias = name`, `max_mode = mode = access_mode`;
   - renomeia a conexão no catálogo para `<nome> (<slug do sistema>)`, truncando o nome
     para caber, o que garante unicidade global sem alterar nenhum alias;
   - remove `system_id`, `access_mode` e a restrição `uq_connection_per_system`; cria a
     unicidade de `name`.
2. Publicar a imagem base nova (proxy e MCP com `schema_admin`) antes do portal novo: o
   campo de modo no manifesto é opcional e a ausência equivale a `read_write`, então a
   imagem nova funciona com o portal antigo e o portal novo com containers antigos.
3. Depois do upgrade, o admin concede DB Manager a quem deve gerir o catálogo. Até lá,
   só o admin cadastra e autoriza conexões.

Rollback: o `downgrade` recoloca `system_id` e `access_mode` a partir das autorizações e
só é possível enquanto cada conexão tiver exatamente uma autorização. Se alguma conexão
já tiver sido compartilhada, o rollback é por restauração do backup do banco do portal.
