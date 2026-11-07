# Spec Delta

## MODIFIED Requirements

### Requirement: Chave por provedor do catálogo
O portal SHALL manter a chave de API por provedor do catálogo de LLM, incluindo provedores OpenAI-compatible cadastrados e o OpenRouter. A chave SHALL ser consumida pelo broker de inferência no caminho de saída e SHALL NOT ser entregue ao container do sistema.

#### Scenario: Admin cadastra chave de provedor custom
- **WHEN** o admin cadastra a chave de um provedor OpenAI-compatible do catálogo
- **THEN** a chave fica associada a esse provedor e é usada pelo broker de inferência para os sistemas que o escolherem

#### Scenario: Container do sistema não recebe a chave
- **WHEN** o portal provisiona o container de um sistema que usa um provedor do catálogo com chave cadastrada
- **THEN** a chave do provedor não é entregue ao container; somente o token opaco do broker é
