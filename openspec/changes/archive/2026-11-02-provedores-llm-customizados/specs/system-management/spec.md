# Spec Delta

## MODIFIED Requirements

### Requirement: Provedor de LLM configurável por sistema
O portal SHALL permitir escolher, no cadastro do sistema, o provedor e o modelo de LLM — dentre os provedores do catálogo — a ser usado pelo seu agente, com provedor padrão GLM quando não informado.

#### Scenario: Cadastro sem escolha de provedor
- **WHEN** um sistema é criado sem provedor informado
- **THEN** o sistema usa o provedor padrão GLM e o modelo padrão associado

#### Scenario: Dono altera provedor do sistema
- **WHEN** o dono altera o provedor/modelo de um sistema existente
- **THEN** as próximas conversas com o agente usam a nova configuração

#### Scenario: Provedor do catálogo disponível na escolha
- **WHEN** um editor cria um sistema ou edita o provedor de um sistema existente
- **THEN** as opções de provedor e modelo vêm do catálogo de provedores