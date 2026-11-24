# Spec Delta

## MODIFIED Requirements

### Requirement: Registro de toda ação de escrita de gestão
O portal SHALL registrar cada ação de escrita da gestão (criar, editar, desativar, vincular, desvincular, remover ou excluir recursos do portal — sistemas, conexões, usuários, grupos, checkpoints e chaves de LLM) com autor, ação, recurso, alvo, sistema relacionado quando houver, detalhes e data. Para conexões de banco, isso SHALL incluir cadastrar, editar e excluir no catálogo, autorizar e revogar para um sistema, alterar o teto, ativar, desativar e alterar o modo de acesso vigente, além de conceder ou retirar a capacidade de DB Manager de um usuário.

#### Scenario: Ação de gestão é registrada
- **WHEN** um admin exclui um grupo
- **THEN** uma entrada de auditoria registra o admin, a ação de exclusão, o grupo alvo e a data

#### Scenario: Autorização de conexão é registrada
- **WHEN** um DB Manager autoriza uma conexão do catálogo para o sistema X com teto `read_write`
- **THEN** uma entrada de auditoria registra o DB Manager, a ação de autorização, a conexão, o sistema X e o teto

#### Scenario: Ativação pelo dono é registrada
- **WHEN** o dono do sistema X ativa uma conexão com alias `vendas` em modo `read_only`
- **THEN** uma entrada de auditoria do sistema X registra o dono, a ação de ativação, o alias e o modo

#### Scenario: Liberação de DDL é rastreável
- **WHEN** um DB Manager eleva o teto para `schema_admin` e depois o dono muda o modo vigente para `schema_admin`
- **THEN** a trilha tem duas entradas, cada uma com seu autor, mostrando quem liberou o teto e quem ativou o modo

#### Scenario: Revogação é registrada no sistema afetado
- **WHEN** um DB Manager revoga a autorização do sistema X
- **THEN** a auditoria do sistema X mostra a revogação com autor e data

#### Scenario: Concessão de DB Manager é registrada
- **WHEN** no modo `local` um admin concede a capacidade de DB Manager a um usuário
- **THEN** uma entrada de auditoria registra o admin, a ação e o usuário alvo
