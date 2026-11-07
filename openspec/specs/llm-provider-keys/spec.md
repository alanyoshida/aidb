# llm-provider-keys Specification

## Purpose
Define a gestão das chaves de API dos provedores de LLM pelo administrador do portal: cadastro, troca, remoção e teste, com a chave armazenada cifrada e global por provedor.

## Requirements

### Requirement: Cadastro de chave de provedor pelo admin
O portal SHALL permitir que o admin cadastre ou troque a chave de API de um provedor de LLM, armazenando-a cifrada e de forma global por provedor, sem exibi-la de volta.

#### Scenario: Admin cadastra chave
- **WHEN** um admin cadastra a chave de um provedor
- **THEN** a chave é armazenada cifrada e a interface indica que há chave configurada, sem revelar seu valor

### Requirement: Remoção de chave de provedor
O portal SHALL permitir que o admin remova a chave cadastrada de um provedor.

#### Scenario: Admin remove chave
- **WHEN** um admin remove a chave de um provedor
- **THEN** o portal deixa de ter chave cadastrada para esse provedor

### Requirement: Teste de chave de provedor
O portal SHALL permitir que o admin teste a chave cadastrada de um provedor com uma chamada mínima ao provedor, reportando sucesso ou falha sem gravar nada.

#### Scenario: Teste bem-sucedido
- **WHEN** o admin testa uma chave válida
- **THEN** o portal reporta sucesso

#### Scenario: Teste falho
- **WHEN** o admin testa uma chave inválida ou sem saldo
- **THEN** o portal reporta a falha sem gravar

### Requirement: Gestão de chaves restrita ao admin
O portal SHALL restringir o cadastro, a troca, a remoção e o teste de chaves de provedor a administradores.

#### Scenario: Não-admin tenta gerenciar chaves
- **WHEN** um editor ou um app_user tenta cadastrar, remover ou testar uma chave de provedor
- **THEN** o portal recusa a operação por permissão insuficiente

### Requirement: Chave por provedor do catálogo
O portal SHALL manter a chave de API por provedor do catálogo de LLM, incluindo provedores OpenAI-compatible cadastrados e o OpenRouter. A chave SHALL ser consumida pelo broker de inferência no caminho de saída e SHALL NOT ser entregue ao container do sistema.

#### Scenario: Admin cadastra chave de provedor custom
- **WHEN** o admin cadastra a chave de um provedor OpenAI-compatible do catálogo
- **THEN** a chave fica associada a esse provedor e é usada pelo broker de inferência para os sistemas que o escolherem

#### Scenario: Container do sistema não recebe a chave
- **WHEN** o portal provisiona o container de um sistema que usa um provedor do catálogo com chave cadastrada
- **THEN** a chave do provedor não é entregue ao container; somente o token opaco do broker é

### Requirement: Teste de chave usa a base_url do provedor
O portal SHALL testar a chave de um provedor do catálogo usando a rota do próprio provedor.

#### Scenario: Teste de provedor OpenAI-compatible
- **WHEN** o admin testa a chave de um provedor OpenAI-compatible
- **THEN** o portal faz a chamada mínima na base_url desse provedor e reporta sucesso ou falha
