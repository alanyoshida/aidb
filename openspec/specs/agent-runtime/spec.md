# agent-runtime Specification

## Purpose

Define qual agente de código roda no container de um sistema e como esse runtime é descrito de forma declarativa — comando, configuração, credencial e caminhos — para que a plataforma suporte mais de um agente sem alterar o provisionamento, a supervisão do container ou as camadas de confinamento construídas sobre ele.

## Requirements

### Requirement: Perfil de runtime por sistema
Cada sistema SHALL ter exatamente um perfil de runtime de agente, determinado no provisionamento, que identifica qual agente roda no seu container. O perfil SHALL ser a fonte única consultada para montar e supervisionar esse runtime.

#### Scenario: Sistema provisionado tem perfil definido
- **WHEN** um sistema é provisionado
- **THEN** o perfil de runtime do seu agente está determinado e é consultável, e o container sobe com o agente que o perfil identifica

#### Scenario: Perfil padrão da plataforma
- **WHEN** um sistema é criado sem que um perfil seja informado
- **THEN** o sistema recebe o perfil padrão da plataforma

### Requirement: Conteúdo declarativo do perfil
O perfil SHALL declarar tudo que a plataforma precisa saber para executar o agente: o comando e o diretório de trabalho, o caminho e o formato do arquivo de configuração do agente, o nome da variável de ambiente pela qual o agente recebe sua credencial de LLM, a porta em que o agente atende o portal, e os caminhos que o agente precisa ler e escrever.

#### Scenario: Provisionamento monta o container a partir do perfil
- **WHEN** o portal provisiona o container de um sistema
- **THEN** o arquivo de configuração do agente, a variável de credencial e a porta esperada do agente vêm do perfil, e não de valores fixados para um agente específico

#### Scenario: Caminhos de leitura e escrita declarados
- **WHEN** o perfil de um agente é consultado
- **THEN** ele informa quais caminhos aquele agente precisa ler e quais precisa escrever, de modo que camadas de confinamento posteriores possam derivar política a partir dele sem conhecer o agente

### Requirement: Perfil entregue ao container sem segredo
O portal SHALL entregar o perfil ao container pelo diretório de configuração do agente, montado somente-leitura e fora do workspace. O perfil entregue SHALL conter apenas o nome da variável de credencial, nunca o valor de nenhum segredo.

#### Scenario: Perfil não carrega segredo
- **WHEN** o perfil entregue ao container é inspecionado
- **THEN** ele não contém chave de provedor, senha de conexão nem qualquer outro segredo, apenas o nome da variável onde a credencial é esperada

#### Scenario: Perfil não é gravável pelo agente
- **WHEN** o agente tenta alterar o perfil entregue
- **THEN** a alteração é recusada, porque o diretório de configuração é montado somente-leitura

### Requirement: Supervisão dirigida pelo perfil
O supervisor do container SHALL subir e manter o agente conforme o perfil entregue, e SHALL NOT embutir o comando, o diretório de trabalho ou a porta de nenhum agente específico.

#### Scenario: Agente sobe conforme o perfil
- **WHEN** o container de um sistema inicia
- **THEN** o supervisor executa o agente com o comando, o diretório de trabalho e a porta declarados no perfil

#### Scenario: Perfil ausente ou ilegível é falha explícita
- **WHEN** o container inicia sem perfil legível
- **THEN** o supervisor não sobe nenhum agente e a falha fica registrada, em vez de recorrer silenciosamente a um agente padrão embutido

### Requirement: Conjunto de perfis extensível
O conjunto de perfis da plataforma SHALL ser extensível: registrar um perfil novo SHALL habilitar o agente correspondente sem exigir alteração no provisionamento do container, no supervisor ou nas camadas de confinamento.

#### Scenario: Perfil novo habilita agente novo
- **WHEN** um perfil de agente novo é registrado na plataforma
- **THEN** um sistema pode ser provisionado com esse perfil e seu container sobe o agente correspondente, sem que o provisionamento ou o supervisor sejam alterados para conhecê-lo
