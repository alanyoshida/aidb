# management-audit Specification

## Purpose
Define a trilha de auditoria das ações de escrita da gestão do portal: o que foi feito, por quem, sobre qual recurso e sistema, e quando — consultável globalmente pelo admin e por sistema.

## Requirements

### Requirement: Registro de toda ação de escrita de gestão
O portal SHALL registrar cada ação de escrita da gestão (criar, editar, desativar, vincular, desvincular, remover ou excluir sistemas, conexões, usuários, grupos, checkpoints e chaves de LLM) com autor, ação, recurso, alvo, sistema relacionado quando houver, detalhes e data. Nas conexões de banco, isso SHALL cobrir o catálogo, as autorizações e seus tetos, a ativação e o modo vigente, e a capacidade de DB Manager.

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

### Requirement: Trilha consultável globalmente pelo admin
O portal SHALL exibir a trilha de auditoria de gestão ao admin numa visão global, com filtro por autor, recurso e ação.

#### Scenario: Admin consulta a trilha
- **WHEN** um admin abre a trilha de auditoria de gestão
- **THEN** vê as entradas registradas e consegue filtrá-las por autor, recurso e ação

### Requirement: Trilha por sistema
O portal SHALL exibir, na auditoria de cada sistema, as ações de gestão relacionadas àquele sistema, junto do histórico do gate de SQL.

#### Scenario: Ações do sistema visíveis
- **WHEN** o dono ou um admin abre a auditoria de um sistema
- **THEN** vê as ações de gestão daquele sistema e o histórico do gate na mesma área

### Requirement: Trilha sem segredos
A trilha de auditoria de gestão SHALL NOT registrar senhas de conexão nem chaves de LLM.

#### Scenario: Edição de conexão não vaza senha
- **WHEN** uma conexão é editada
- **THEN** a entrada de auditoria descreve a alteração sem conter a senha
