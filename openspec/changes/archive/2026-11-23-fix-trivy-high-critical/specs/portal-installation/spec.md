## ADDED Requirements

### Requirement: Portal do chart com contexto de segurança restrito
O chart SHALL instalar o portal e o initContainer das migrações sem nenhuma capability, sem escalada de privilégio, com perfil seccomp `RuntimeDefault` e raiz somente leitura. Tudo o que o portal grava SHALL ficar em volumes.

#### Scenario: Portal sem capabilities e sem escrita na raiz
- **WHEN** o chart é instalado com os valores padrão
- **THEN** o container do portal roda sem capabilities, sem escalada de privilégio e com a raiz somente leitura, e responde no endpoint de saúde

#### Scenario: Sistema criado e chat com o portal endurecido
- **WHEN** um sistema é criado pelo portal instalado pelo chart e o agente fake atende um pedido no chat
- **THEN** a execução termina sem erro e o checkpoint dela aparece no sistema

### Requirement: Postgres do chart com contexto de segurança restrito
O chart SHALL instalar o Postgres do portal sem escalada de privilégio, com perfil seccomp `RuntimeDefault`, raiz somente leitura e só as capabilities de que o entrypoint da imagem oficial precisa: `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `SETGID` e `SETUID`. Um upgrade de uma instalação anterior SHALL preservar o banco.

#### Scenario: Upgrade preserva o banco
- **WHEN** uma instalação feita com o chart anterior é atualizada para esta versão
- **THEN** o Postgres sobe com o contexto restrito sobre a mesma PVC, os dados gravados antes continuam lá e as migrações rodam no initContainer
