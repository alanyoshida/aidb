# management-audit Specification

## Purpose
Define a trilha de auditoria das ações de escrita da gestão do portal: o que foi feito, por quem, sobre qual recurso e sistema, e quando — consultável globalmente pelo admin e por sistema.

## Requirements

### Requirement: Registro de toda ação de escrita de gestão
O portal SHALL registrar cada ação de escrita da gestão (criar, editar, desativar, vincular, desvincular, remover ou excluir recursos do portal — sistemas, conexões, usuários, grupos, checkpoints e chaves de LLM) com autor, ação, recurso, alvo, sistema relacionado quando houver, detalhes e data.

#### Scenario: Ação de gestão é registrada
- **WHEN** um admin exclui um grupo
- **THEN** uma entrada de auditoria registra o admin, a ação de exclusão, o grupo alvo e a data

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
