# agent-telemetry Specification

## Purpose

Dá observabilidade de ponta a ponta sobre a execução do agente e sobre ações sensíveis do portal (login, configuração de sistema, prompts), por meio de rastreamento distribuído e logs centralizados, sem alterar os registros de auditoria e de gate já existentes.

## Requirements

### Requirement: Rastreamento distribuído por execução do agente
Cada execução do agente (`run_id`) SHALL produzir um span raiz que permanece aberto do início ao fim da execução, ao qual se anexam spans filhos representando as operações realizadas durante a execução (consultas ao banco, chamadas de ferramenta, decisões do gate, chamadas de LLM).

#### Scenario: Execução simples sem operações filhas
- **WHEN** uma execução do agente inicia e termina sem disparar nenhuma consulta ao banco, ferramenta ou chamada de LLM
- **THEN** o span raiz da execução é aberto no início e encerrado no fim, sem spans filhos

#### Scenario: Execução com consulta ao banco
- **WHEN** o agente executa uma consulta SQL durante uma execução em andamento
- **THEN** um span de consulta é criado como filho do span raiz daquela execução, correlacionado ao mesmo `run_id`

#### Scenario: Execução interrompida ou com erro
- **WHEN** uma execução do agente é interrompida pelo usuário ou termina em erro
- **THEN** o span raiz daquela execução é encerrado refletindo o motivo do encerramento, e nenhum span filho permanece aberto após esse ponto

### Requirement: Correlação de consultas ao banco com a execução em curso
Toda consulta ao banco realizada por um sistema SHALL ser correlacionada à execução do agente em curso naquele sistema no momento da consulta, quando houver uma execução em curso.

#### Scenario: Consulta durante execução ativa
- **WHEN** o sidecar de banco de um sistema envia uma consulta para classificação enquanto aquele sistema tem uma execução de agente em curso
- **THEN** o span da consulta é anexado ao span raiz daquela execução

#### Scenario: Consulta sem execução em curso
- **WHEN** o sidecar de banco de um sistema envia uma consulta para classificação e aquele sistema não tem nenhuma execução de agente em curso
- **THEN** a consulta é classificada e registrada normalmente, sem ser associada a nenhum span de execução

### Requirement: Observabilidade opcional no deploy
A infraestrutura de observabilidade (coleta de traços, métricas e logs, e sua visualização) SHALL ser opcional na implantação, e sua ausência SHALL NOT impedir ou degradar o funcionamento normal do portal, do broker ou dos sistemas provisionados.

#### Scenario: Deploy sem o stack de observabilidade
- **WHEN** o ambiente é implantado sem o stack de observabilidade habilitado
- **THEN** o portal, o broker e os sistemas provisionados continuam operando normalmente, sem erros relacionados à ausência do stack

#### Scenario: Deploy com o stack de observabilidade
- **WHEN** o ambiente é implantado com o stack de observabilidade habilitado
- **THEN** traços, métricas e logs emitidos pelo portal e pelo broker passam a ser coletados e ficam disponíveis para visualização

### Requirement: Exportação de telemetria agnóstica de backend
A exportação de traços e logs do portal e do broker SHALL ser sempre direcionada a um endpoint de Collector fixo e configurável por variável de ambiente; a escolha de qual backend de observabilidade recebe esses dados (Grafana Tempo/Loki, Elastic, ou outro) SHALL ser determinada pela configuração do Collector, não pelo código ou pela configuração da aplicação.

#### Scenario: Troca de backend de observabilidade
- **WHEN** o Collector é reconfigurado para exportar para um backend diferente do atual (ex.: de Grafana Tempo/Loki para Elasticsearch/Kibana)
- **THEN** nenhuma mudança é necessária no código ou na configuração do portal e do broker

#### Scenario: Collector não configurado
- **WHEN** o endpoint do Collector não está definido
- **THEN** o SDK de telemetria permanece no-op, como já ocorre hoje sem endpoint configurado

### Requirement: Debug log do chat reflete o rastreamento quando disponível
O Debug log de uma sessão de chat SHALL exibir a árvore de spans da execução correspondente sempre que houver spans persistidos para aquela execução, independente de qualquer backend de observabilidade externo estar configurado ou não. Quando não houver spans persistidos para aquela execução, o Debug log SHALL continuar exibindo o comportamento atual baseado em eventos em memória, sem regressão.

#### Scenario: Debug log com stack habilitado
- **WHEN** o usuário abre o Debug log de uma sessão cuja execução já aconteceu e produziu spans persistidos
- **THEN** o Debug log exibe a árvore de spans daquela execução, incluindo consultas ao banco, chamadas de ferramenta e chamadas de LLM associadas, lendo da tabela de spans em Postgres, sem consultar nenhum backend de observabilidade externo

#### Scenario: Debug log sem stack habilitado
- **WHEN** o usuário abre o Debug log de uma sessão cuja execução não produziu nenhum span persistido
- **THEN** o Debug log exibe os eventos em memória da execução, como hoje

### Requirement: Retenção dos spans persistidos para o Debug log
Os spans persistidos para uso do Debug log SHALL ser removidos automaticamente após um período de retenção configurável, para limitar o crescimento da tabela que os armazena.

#### Scenario: Span além do período de retenção
- **WHEN** um span persistido ultrapassa o período de retenção configurado
- **THEN** ele é removido pela limpeza automática, e deixa de aparecer no Debug log de execuções antigas

### Requirement: Log de tentativas de autenticação
Toda tentativa de autenticação no portal, bem-sucedida ou não, SHALL ser registrada em um log centralizado, incluindo o identificador ou e-mail informado e o resultado da tentativa.

#### Scenario: Login bem-sucedido
- **WHEN** um usuário se autentica com credenciais válidas
- **THEN** uma entrada de log é registrada indicando sucesso e o identificador do usuário autenticado

#### Scenario: Tentativa de login falha
- **WHEN** uma tentativa de autenticação é feita com credenciais inválidas
- **THEN** uma entrada de log é registrada indicando falha, sem incluir a senha ou qualquer segredo informado

### Requirement: Log de mudanças de configuração de rede do sistema
Toda mudança na configuração de rede de um sistema (habilitar/desabilitar internet, ativar/desativar modo restrito, adicionar ou remover domínio da allow-list) SHALL ser registrada em um log centralizado, incluindo o sistema afetado, o autor da mudança e o valor resultante.

#### Scenario: Alternar modo restrito
- **WHEN** um editor ativa ou desativa o modo restrito de rede de um sistema
- **THEN** uma entrada de log é registrada com o sistema, o autor e o novo estado do modo restrito

#### Scenario: Adicionar domínio à allow-list
- **WHEN** um editor adiciona um domínio à allow-list de um sistema
- **THEN** uma entrada de log é registrada com o sistema, o autor e o domínio adicionado

### Requirement: Log de mudanças no ciclo de vida do sistema
Toda transição de ciclo de vida de um sistema (arquivamento, exclusão, ou mudança de status) SHALL ser registrada em um log centralizado, incluindo o sistema afetado, o autor quando aplicável, e o estado resultante.

#### Scenario: Arquivar sistema
- **WHEN** um sistema é arquivado
- **THEN** uma entrada de log é registrada com o sistema afetado e o estado resultante

#### Scenario: Excluir sistema
- **WHEN** um sistema é excluído
- **THEN** uma entrada de log é registrada com o sistema afetado antes da remoção de seus dados

### Requirement: Log de prompts enviados no chat
Todo prompt enviado por um usuário em uma sessão de chat SHALL ser registrado em um log centralizado, correlacionado ao sistema e à sessão de chat correspondentes.

#### Scenario: Envio de prompt
- **WHEN** um usuário envia uma mensagem em uma sessão de chat
- **THEN** uma entrada de log é registrada com o conteúdo do prompt, o sistema e a sessão correspondentes

### Requirement: Espelho das ações administrativas em log centralizado
Toda ação administrativa já registrada na auditoria de gestão (`management-audit`) SHALL também ser emitida como entrada de log centralizado, com o mesmo conteúdo sanitizado (sem segredos) já aplicado ao registro de auditoria.

#### Scenario: Ação administrativa registrada em auditoria
- **WHEN** uma ação administrativa é registrada na auditoria de gestão
- **THEN** a mesma ação é também emitida como entrada de log centralizado, com os mesmos campos sanitizados

### Requirement: Não substituição dos registros de auditoria e de gate existentes
Esta capacidade SHALL NOT substituir, remover ou se tornar a fonte de verdade dos registros já existentes de decisões do gate de operações destrutivas (`GateDecision`) ou da auditoria de gestão (`ManagementAudit`); ambos continuam sendo a fonte de verdade para fins de compliance.

#### Scenario: Consulta de decisão de gate após esta capacidade existir
- **WHEN** um administrador consulta o histórico de decisões do gate de um sistema
- **THEN** o resultado continua vindo do registro permanente de decisões do gate, sem depender da disponibilidade do stack de observabilidade

#### Scenario: Consulta da auditoria de gestão após esta capacidade existir
- **WHEN** um administrador consulta a auditoria de gestão de um sistema ou globalmente
- **THEN** o resultado continua vindo do registro permanente de auditoria de gestão, sem depender da disponibilidade do stack de observabilidade
