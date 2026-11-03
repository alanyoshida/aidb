# Spec Delta

## ADDED Requirements

### Requirement: Renomeação de sistema pelo dono
O portal SHALL permitir que o dono (ou um admin) altere o nome de exibição de um sistema existente, mantendo o slug imutável.

#### Scenario: Dono renomeia o sistema
- **WHEN** o dono altera o nome de um sistema existente
- **THEN** o novo nome passa a ser exibido em todo o portal e o slug (URL `/apps/<slug>`) permanece o mesmo

### Requirement: Transferência de posse ao excluir usuário
O portal SHALL transferir a posse dos sistemas de um usuário excluído para o administrador que executa a exclusão, de modo que todo sistema permaneça com um dono válido.

#### Scenario: Sistemas do usuário excluído são transferidos
- **WHEN** um admin exclui um usuário que possui sistemas
- **THEN** esses sistemas passam a ter o admin executor como dono