# Spec Delta

## ADDED Requirements

### Requirement: Exclusão de usuário pelo admin
O portal SHALL permitir que o admin exclua um usuário após confirmação, removendo seus vínculos de grupo e transferindo a posse dos sistemas dele conforme a capability system-management.

#### Scenario: Admin exclui usuário
- **WHEN** um admin confirma a exclusão de um usuário
- **THEN** o usuário é removido, seus vínculos de grupo são apagados e a posse de seus sistemas é transferida

#### Scenario: Histórico permanece após a exclusão
- **WHEN** um admin exclui um usuário que possui histórico (execuções, uso de tokens, checkpoints e decisões do gate)
- **THEN** o histórico permanece, atribuído ao e-mail do usuário excluído, sem depender da referência à tabela de usuários

### Requirement: Gestão de grupos pelo admin
O portal SHALL permitir que o admin renomeie e exclua grupos, remova membros de um grupo e desvincule sistemas de um grupo. Excluir um grupo remove seus vínculos sem excluir sistemas ou usuários.

#### Scenario: Admin renomeia grupo
- **WHEN** um admin altera o nome de um grupo
- **THEN** o grupo passa a ter o novo nome

#### Scenario: Admin remove membro
- **WHEN** um admin remove um usuário de um grupo
- **THEN** o usuário deixa de ser membro do grupo

#### Scenario: Admin desvincula sistema
- **WHEN** um admin desvincula um sistema de um grupo
- **THEN** os membros do grupo deixam de acessar aquele sistema

#### Scenario: Admin exclui grupo
- **WHEN** um admin confirma a exclusão de um grupo
- **THEN** o grupo e seus vínculos são removidos, preservando os sistemas e usuários