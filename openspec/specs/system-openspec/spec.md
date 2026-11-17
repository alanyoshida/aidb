# system-openspec Specification

## Purpose

Garante que o agente de código de cada sistema tenha o OpenSpec disponível e pré-configurado no seu ambiente, para que o editor possa conduzir mudanças planejadas (proposta, specs, design, tarefas) pelo chat do portal.

## Requirements

### Requirement: CLI do OpenSpec disponível ao agente
O ambiente do agente de cada sistema SHALL ter o CLI do OpenSpec em versão fixa disponível para execução, sem depender de acesso à rede no momento do uso.

#### Scenario: Agente executa o CLI
- **WHEN** o agente do sistema executa `openspec --version` no workspace
- **THEN** o comando responde com a versão fixada pela plataforma

#### Scenario: Sem rede externa
- **WHEN** o proxy de saída do sistema não libera nenhum domínio de registro de pacotes
- **THEN** o CLI do OpenSpec continua funcionando no ambiente do agente

### Requirement: Workspace inicializado com OpenSpec
Ao iniciar o ambiente de um sistema, a plataforma SHALL garantir que o workspace esteja inicializado com OpenSpec configurado para o agente — diretório `openspec/` e comandos `/opsx-*` reconhecidos pelo agente —, com artefatos escritos em português do Brasil, sem ação do editor.

#### Scenario: Sistema novo já sobe configurado
- **WHEN** um sistema é criado e seu ambiente fica ativo
- **THEN** o workspace contém o diretório `openspec/` e os comandos `/opsx-propose`, `/opsx-explore`, `/opsx-apply` e `/opsx-archive` disponíveis ao agente

#### Scenario: Sistema existente ganha OpenSpec ao reiniciar
- **WHEN** o ambiente de um sistema criado antes desta mudança é reiniciado ou recriado
- **THEN** o workspace passa a ter OpenSpec configurado, e a app e os demais arquivos existentes permanecem intactos

### Requirement: Inicialização preserva o trabalho do OpenSpec
A inicialização SHALL ser idempotente: num workspace já inicializado, SHALL preservar todas as changes, specs e configuração existentes em `openspec/`, atualizando apenas os comandos e skills do agente para a versão do CLI da plataforma.

#### Scenario: Reinício não apaga changes
- **WHEN** um workspace com uma change em andamento em `openspec/changes/` é reiniciado
- **THEN** a change e seus artefatos continuam presentes e inalterados

#### Scenario: Falha na inicialização não derruba o sistema
- **WHEN** a inicialização do OpenSpec falha
- **THEN** o agente e a app do sistema sobem normalmente e a falha fica registrada no log do ambiente

### Requirement: Comandos OpenSpec utilizáveis pelo chat do portal
Um comando `/opsx-*` enviado pelo editor no chat do portal SHALL ser executado pelo agente do sistema como comando do OpenSpec, produzindo os artefatos no workspace do sistema.

#### Scenario: Editor propõe uma change pelo chat
- **WHEN** o editor envia `/opsx-propose adicionar filtro por data` no chat de um sistema
- **THEN** o agente cria a change em `openspec/changes/` do workspace com proposta, specs, design e tarefas

#### Scenario: Checkpoint inclui os artefatos
- **WHEN** a execução que criou a change termina com sucesso
- **THEN** o checkpoint git da execução inclui os arquivos da change
