# llm-provider-catalog Specification

## Purpose

Define o catálogo de provedores de LLM do portal: cadastro pelo admin de provedores que falam o padrão OpenAI (com o OpenRouter como preset), descoberta dos modelos na própria rota do provedor e provisão do provedor escolhido ao agente de cada sistema.

## Requirements

### Requirement: Cadastro de provedor de LLM pelo admin
O portal SHALL permitir que o admin cadastre provedores de LLM OpenAI-compatible informando id, rótulo e base_url, e SHALL disponibilizar o OpenRouter como provedor preset, sem exigir alteração de código.

#### Scenario: Admin cadastra provedor OpenAI-compatible
- **WHEN** o admin cadastra um provedor com id, rótulo e base_url
- **THEN** o provedor passa a aparecer no catálogo e pode ser escolhido pelos sistemas

#### Scenario: OpenRouter disponível como preset
- **WHEN** um admin ou um editor abre a escolha de provedor de um sistema
- **THEN** o OpenRouter aparece entre as opções

### Requirement: Descoberta de modelos na rota do provedor
O portal SHALL obter a lista de modelos de um provedor a partir da rota de modelos do próprio provedor, usando a chave cadastrada, e SHALL usá-la na escolha de modelo do sistema.

#### Scenario: Admin busca os modelos de um provedor
- **WHEN** o admin aciona a busca de modelos de um provedor cadastrado
- **THEN** a lista de modelos do provedor é obtida e guardada para seleção

### Requirement: Edição e remoção de provedor
O portal SHALL permitir que o admin edite rótulo, base_url e modelos de um provedor e remova provedores cadastrados, e SHALL NOT permitir a remoção dos provedores preset.

#### Scenario: Admin remove um provedor custom
- **WHEN** o admin remove um provedor cadastrado que não é preset
- **THEN** o provedor deixa de aparecer no catálogo

#### Scenario: Preset não é removível
- **WHEN** o admin tenta remover um provedor preset
- **THEN** o portal recusa a remoção

### Requirement: Provisão do provedor ao agente do sistema
O portal SHALL provisionar ao agente do sistema o provedor escolhido, informando a configuração do provedor — para OpenAI-compatible, o endpoint compatível com a base_url e os modelos — e a credencial correspondente.

#### Scenario: Sistema usa provedor OpenAI-compatible
- **WHEN** um sistema é provisionado com um provedor OpenAI-compatible
- **THEN** o agente do sistema recebe a configuração com a base_url e a credencial do provedor

### Requirement: Gestão do catálogo restrita ao admin
O portal SHALL restringir o cadastro, a edição, a remoção e a busca de modelos dos provedores do catálogo a administradores.

#### Scenario: Não-admin tenta gerenciar o catálogo
- **WHEN** um editor ou um app_user tenta cadastrar, editar ou remover um provedor
- **THEN** o portal recusa a operação por permissão insuficiente
