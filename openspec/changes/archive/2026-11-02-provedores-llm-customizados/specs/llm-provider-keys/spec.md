# Spec Delta

## ADDED Requirements

### Requirement: Chave por provedor do catálogo
O portal SHALL manter a chave de API por provedor do catálogo de LLM, incluindo provedores OpenAI-compatible cadastrados e o OpenRouter.

#### Scenario: Admin cadastra chave de provedor custom
- **WHEN** o admin cadastra a chave de um provedor OpenAI-compatible do catálogo
- **THEN** a chave fica associada a esse provedor e é usada no provisionamento dos sistemas que o escolherem

### Requirement: Teste de chave usa a base_url do provedor
O portal SHALL testar a chave de um provedor do catálogo usando a rota do próprio provedor.

#### Scenario: Teste de provedor OpenAI-compatible
- **WHEN** o admin testa a chave de um provedor OpenAI-compatible
- **THEN** o portal faz a chamada mínima na base_url desse provedor e reporta sucesso ou falha