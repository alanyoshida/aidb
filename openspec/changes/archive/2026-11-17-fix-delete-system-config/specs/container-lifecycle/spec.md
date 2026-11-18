## MODIFIED Requirements

### Requirement: Arquivamento e exclusão de sistema
O portal SHALL permitir que o dono arquive seu sistema — desativando acessos e o container, preservando o workspace — e que somente administradores executem a exclusão definitiva, removendo container, workspace e a config do sistema gerada pelo portal.

#### Scenario: Dono arquiva sistema
- **WHEN** o dono arquiva um sistema
- **THEN** o container para, o sistema sai das listas de acesso e o workspace permanece guardado

#### Scenario: Admin exclui definitivamente
- **WHEN** um admin exclui um sistema arquivado
- **THEN** container e workspace são removidos permanentemente

#### Scenario: Exclusão não deixa config órfã
- **WHEN** um admin exclui definitivamente um sistema
- **THEN** a pasta de config do sistema no portal (config do agente e perfil de runtime) também é removida
- **AND** outro sistema não é afetado
