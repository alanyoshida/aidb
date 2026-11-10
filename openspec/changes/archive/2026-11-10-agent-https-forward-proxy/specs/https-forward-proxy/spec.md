# Spec Delta

## Purpose

Garante que toda saída HTTP(S) do container de um sistema atravesse um proxy que só libera os
destinos calculados para aquele sistema, fechando o canal de rede que ficava aberto em 443/80.

## ADDED Requirements

### Requirement: Proxy obrigatório na saída HTTP(S) do sistema
O provisionamento SHALL colocar, para cada sistema, um proxy HTTP(S) de saída no mesmo namespace de rede do container do sistema, e SHALL ser o único caminho de saída nas portas 443/80 disponível ao agente.

#### Scenario: Conexão ao destino permitido funciona pelo proxy
- **WHEN** um processo dentro do container do sistema faz `CONNECT` ao proxy para um `host:443` que está na allow-list calculada para aquele sistema
- **THEN** o proxy abre a conexão real com o destino e repassa os bytes nos dois sentidos sem alterar o conteúdo

#### Scenario: Conexão direta às portas 443/80 continua negada
- **WHEN** um processo dentro do container do sistema tenta abrir uma conexão TCP de saída direto na porta 443 ou 80, sem passar pelo proxy
- **THEN** a tentativa falha por permissão negada — a mesma camada de confinamento de rede da etapa 5 (`agent-sandbox`) só libera a porta do proxy, não 443/80 diretamente

### Requirement: Allow-list padrão de destino calculada por sistema
Quando a internet está habilitada e o modo restrito está desligado para um sistema (comportamento padrão), o proxy SHALL recusar qualquer `CONNECT` ou requisição HTTP para um destino (`host:porta`) que não esteja na allow-list calculada para aquele sistema, sem jamais decriptar ou inspecionar o conteúdo da conexão.

#### Scenario: Destino fora da allow-list padrão é recusado
- **WHEN** um processo dentro do container do sistema pede ao proxy um destino que não está na allow-list padrão daquele sistema
- **THEN** o proxy recusa a conexão com um erro de proxy claro, sem abrir conexão nenhuma com esse destino

#### Scenario: Allow-list padrão inclui o provedor de LLM ou o broker, nunca os dois
- **WHEN** a allow-list padrão de um sistema é calculada
- **THEN** ela inclui o host do provedor de LLM nativo ou customizado configurado para aquele sistema quando o broker de inferência está desligado para ele, ou o host:porta do broker quando está ligado — nunca os dois ao mesmo tempo

#### Scenario: Allow-list padrão inclui os registros de pacote, iguais para todo sistema
- **WHEN** a allow-list padrão de qualquer sistema é calculada
- **THEN** ela inclui os hosts de registro de pacote (`pip`/`npm`/`uv`) usados pela plataforma, independente da configuração daquele sistema

### Requirement: Internet habilitada ou desabilitada por sistema
O portal SHALL manter, por sistema, um controle "internet habilitada" (padrão: habilitada) editável pelo editor do sistema; desabilitado, o proxy SHALL recusar qualquer destino externo, independente da allow-list padrão ou da lista do modo restrito.

#### Scenario: Internet desabilitada recusa todo destino externo
- **WHEN** o controle de internet de um sistema está desabilitado e um processo dentro do container pede ao proxy qualquer destino externo
- **THEN** o proxy recusa a conexão, mesmo que o destino estivesse na allow-list padrão ou na lista do modo restrito

#### Scenario: Broker de inferência continua funcionando com a internet desabilitada
- **WHEN** o controle de internet de um sistema está desabilitado e o broker de inferência está habilitado para aquele sistema
- **THEN** o agente continua conseguindo usar o LLM pelo broker normalmente — o broker é alcançado por uma porta liberada à parte (fora deste proxy), não afetada por este controle

### Requirement: Modo restrito com lista de domínios customizada por sistema
O portal SHALL manter, por sistema, um controle "modo restrito" (padrão: desligado) e uma lista de domínios cadastrados pelo editor do sistema; ligado, o proxy SHALL substituir inteiramente a allow-list padrão pela lista cadastrada, liberando `CONNECT` só para os domínios dela.

#### Scenario: Modo restrito libera só os domínios cadastrados
- **WHEN** o modo restrito de um sistema está ligado e um processo dentro do container pede ao proxy um destino que não está na lista de domínios cadastrada daquele sistema
- **THEN** o proxy recusa a conexão, mesmo que o destino estivesse na allow-list padrão (provedor de LLM, broker ou registro de pacote)

#### Scenario: Lista do modo restrito vem pré-populada com os registros de pacote mais usados
- **WHEN** o modo restrito de um sistema é ligado pela primeira vez, ou o sistema é criado
- **THEN** a lista de domínios daquele sistema já contém os hosts de registro de pacote mais usados (PyPI, npm), editável pelo editor a partir daí

#### Scenario: Internet desabilitada tem prioridade sobre o modo restrito
- **WHEN** o controle de internet de um sistema está desabilitado e o modo restrito está ligado
- **THEN** o proxy recusa todo destino externo, independente do que esteja cadastrado na lista do modo restrito

### Requirement: Ferramentas de linha de comando usam o proxy sem configuração manual
O ambiente do container do sistema SHALL ter as variáveis de proxy HTTP(S) configuradas apontando para o proxy do sistema, de forma que ferramentas que respeitam essa convenção (`pip`, `npm`, `uv`, o cliente HTTP do agente) usem o proxy sem qualquer configuração adicional.

#### Scenario: Instalação de pacote funciona sem configuração extra
- **WHEN** o agente roda `pip install` ou `npm install` para um pacote hospedado num registro permitido
- **THEN** a instalação funciona normalmente, usando o proxy por trás das variáveis de ambiente, sem exigir nenhuma flag ou configuração adicional do agente
