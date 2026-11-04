# Spec Delta

## MODIFIED Requirements

### Requirement: Teste de conexão antes de salvar
O portal SHALL testar a conectividade e as credenciais antes de confirmar o cadastro de uma conexão, e SHALL informar o motivo relatado pelo driver quando o teste falhar, sem expor a senha.

#### Scenario: Conexão válida
- **WHEN** o dono salva uma conexão cujas credenciais acessam o banco informado
- **THEN** o portal confirma o cadastro após teste bem-sucedido

#### Scenario: Conexão inválida
- **WHEN** o dono tenta salvar uma conexão com host inacessível ou credenciais erradas
- **THEN** o portal recusa o cadastro informando que o teste falhou, junto do motivo relatado pelo driver, incluindo host e porta quando o driver os informar

#### Scenario: Senha não aparece na mensagem de erro
- **WHEN** o driver inclui a senha no texto do erro que motivou a falha
- **THEN** o portal remove a senha antes de exibir a mensagem ao usuário
