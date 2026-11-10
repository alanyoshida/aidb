# Spec Delta

## MODIFIED Requirements

### Requirement: Conteúdo declarativo do perfil
O perfil SHALL declarar tudo que a plataforma precisa saber para executar o agente: o comando e o diretório de trabalho, a imagem de container em que o agente roda, o caminho e o formato do arquivo de configuração do agente, o nome da variável de ambiente pela qual o agente recebe sua credencial de LLM, a porta em que o agente atende o portal, e os caminhos que o agente precisa ler e escrever.

#### Scenario: Provisionamento monta o container a partir do perfil
- **WHEN** o portal provisiona o container de um sistema
- **THEN** a imagem do container, o arquivo de configuração do agente, a variável de credencial e a porta esperada do agente vêm do perfil, e não de valores fixados para um agente específico

#### Scenario: Caminhos de leitura e escrita declarados
- **WHEN** o perfil de um agente é consultado
- **THEN** ele informa quais caminhos aquele agente precisa ler e quais precisa escrever, de modo que camadas de confinamento posteriores possam derivar política a partir dele sem conhecer o agente

#### Scenario: Imagem de container declarada no perfil
- **WHEN** dois sistemas usam perfis de agente diferentes
- **THEN** cada um sobe com a imagem de container que o seu próprio perfil declara, mesmo que as duas imagens sejam diferentes

## ADDED Requirements

### Requirement: Driver do portal dirigido pelo perfil
O componente do portal que executa e acompanha uma sessão do agente de um sistema SHALL se conectar ao endereço e usar o protocolo que o perfil daquele sistema declara, e não um endereço ou protocolo fixado para toda a plataforma.

#### Scenario: Dois sistemas com perfis diferentes executam concorrentemente
- **WHEN** dois sistemas com perfis de agente diferentes têm execuções em andamento ao mesmo tempo
- **THEN** cada execução se conecta ao endereço e usa o protocolo que o perfil do seu próprio sistema declara, sem que um sistema afete a conexão usada pelo outro

#### Scenario: Porta de conexão do agente vem do perfil
- **WHEN** o portal precisa se conectar ao agente de um sistema para iniciar ou acompanhar uma execução
- **THEN** a porta usada é a que o perfil daquele sistema declara, e não um valor único fixado para toda a plataforma
