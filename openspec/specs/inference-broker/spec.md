# inference-broker Specification

## Purpose
Garante que nenhuma credencial real de provedor de LLM chegue ao container do sistema: o agente carrega apenas um token opaco, e um broker compartilhado valida esse token, resolve a execução ativa e injeta a credencial somente no caminho de saída.

## Requirements

### Requirement: Token opaco no container do sistema
O provisionamento SHALL entregar ao container do sistema apenas um token opaco emitido pelo portal na variável de credencial do perfil do agente, e SHALL NOT entregar a chave real do provedor nem a virtual key do backend de LLM.

#### Scenario: Ambiente do container não contém chave utilizável
- **WHEN** o ambiente de um container de sistema é inspecionado
- **THEN** a variável de credencial de LLM contém somente o token opaco, sem chave de provedor nem virtual key que permita chamada direta

#### Scenario: Token não é a credencial do provedor
- **WHEN** o token opaco do container é usado diretamente contra o provedor de LLM, fora do broker
- **THEN** o provedor recusa a chamada por credencial inválida

### Requirement: Broker de inferência compartilhado
O portal SHALL operar um broker de inferência compartilhado que valida o token opaco recebido, identifica o sistema correspondente e encaminha a requisição ao backend de LLM com a credencial real injetada no caminho de saída.

#### Scenario: Requisição autenticada é encaminhada
- **WHEN** o agente de um sistema envia uma requisição ao broker com seu token opaco válido
- **THEN** o broker identifica o sistema e encaminha a requisição ao backend de LLM usando a credencial do provedor desse sistema

#### Scenario: Requisição sem token válido é recusada
- **WHEN** uma requisição chega ao broker sem token opaco válido
- **THEN** o broker a recusa sem encaminhar nada ao backend de LLM

### Requirement: Descarte de credencial enviada pelo cliente
O broker SHALL descartar qualquer credencial de provedor enviada pelo próprio cliente e usar somente a credencial que ele injeta.

#### Scenario: Credencial do cliente é ignorada
- **WHEN** o agente envia uma requisição com um header de credencial próprio
- **THEN** o broker o substitui pela credencial do sistema e o backend de LLM recebe apenas a credencial injetada

### Requirement: Atribuição de run e sessão
O broker SHALL resolver, junto ao portal, qual run e qual sessão de chat estão ativos para o sistema identificado pelo token, e SHALL atribuir a requisição a essa execução.

#### Scenario: Requisição é atribuída à execução ativa
- **WHEN** o broker recebe uma requisição de um sistema com execução ativa
- **THEN** a requisição é atribuída ao run e à sessão ativos daquele sistema

#### Scenario: Sistema sem execução ativa
- **WHEN** o broker recebe uma requisição de um sistema que não tem execução ativa
- **THEN** o broker recusa a requisição sem encaminhá-la ao backend de LLM

### Requirement: Streaming e cancelamento transparentes
O broker SHALL repassar respostas em streaming sem bufferizar o conteúdo, preservando a ordem dos eventos, e SHALL propagar o cancelamento da execução ao backend de LLM.

#### Scenario: Streaming chega incrementalmente
- **WHEN** o agente faz uma requisição em streaming
- **THEN** os eventos chegam ao agente incrementalmente, sem acumular a resposta inteira antes de repassar

#### Scenario: Cancelamento interrompe o provedor
- **WHEN** a execução é interrompida no portal
- **THEN** o broker encerra a requisição em andamento junto ao backend de LLM

### Requirement: Revogação centralizada e seletiva
O broker SHALL ser a autoridade única de revogação de acesso à inferência, permitindo revogar o acesso de um sistema ou de uma sessão sem afetar os demais sistemas e sessões.

#### Scenario: Revogar um sistema não afeta os outros
- **WHEN** o acesso de um sistema é revogado no broker
- **THEN** as requisições desse sistema passam a ser recusadas e os demais sistemas continuam funcionando

#### Scenario: Revogar uma sessão mantém o sistema
- **WHEN** o mapeamento de uma sessão é revogado
- **THEN** as requisições atribuídas a essa sessão são recusadas sem derrubar as demais sessões do mesmo sistema

### Requirement: Allowlist de destino do broker
O broker SHALL encaminhar requisições somente para os destinos de LLM permitidos pela configuração da plataforma, recusando qualquer outro destino.

#### Scenario: Destino fora da allowlist é recusado
- **WHEN** uma requisição tenta alcançar um destino de LLM que não está na allowlist do broker
- **THEN** o broker recusa a requisição sem encaminhá-la

### Requirement: Uso de tokens e custo normalizados
O portal SHALL registrar o uso de tokens e o custo de cada execução a partir das informações normalizadas do backend de LLM, sem contagem própria por provedor.

#### Scenario: Uso é registrado por execução
- **WHEN** uma requisição de inferência é concluída
- **THEN** o consumo de tokens e o custo são registrados para o run e a sessão correspondentes

#### Scenario: Uso em streaming também é registrado
- **WHEN** uma requisição em streaming é concluída
- **THEN** o consumo de tokens e o custo também são registrados para o run e a sessão correspondentes
