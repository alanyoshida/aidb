## MODIFIED Requirements

### Requirement: Guidelines editáveis pelo admin
O portal SHALL manter um documento de guidelines de geração, editável por administradores, aplicado a todos os agentes de sistema a partir das próximas execuções após alteração.

#### Scenario: Atualização de guideline propaga
- **WHEN** um admin altera as guidelines
- **THEN** as execuções seguintes em todos os sistemas passam a usar a versão atualizada

#### Scenario: Guidelines chegam ao agente opencode
- **WHEN** um sistema com perfil `opencode` executa um pedido do editor
- **THEN** o conteúdo do `AGENTS.md` materializado no workspace faz parte das instruções enviadas ao modelo, mesmo com o agente rodando fora do workspace
- **AND** nenhuma config de projeto gravável pelo agente (`/workspace/.opencode/opencode.json`, `/workspace/opencode.json`) passa a ser carregada
