# Spec Delta

## MODIFIED Requirements

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

#### Scenario: Chamada de LLM inclui a chamada ao provedor
- **WHEN** o broker encaminha uma chamada de LLM de uma execução em andamento ao provedor
- **THEN** a chamada HTTP ao provedor aparece como span filho do span de chamada de LLM daquela execução, no mesmo traço do span raiz

### Requirement: Exportação de telemetria agnóstica de backend
A exportação de traços, métricas e logs do portal e do broker SHALL ser sempre direcionada a um endpoint de Collector fixo e configurável por variável de ambiente; a escolha de qual backend de observabilidade recebe esses dados (Grafana Tempo/Loki/Prometheus, Elastic, ou outro) SHALL ser determinada pela configuração do Collector, não pelo código ou pela configuração da aplicação.

#### Scenario: Troca de backend de observabilidade
- **WHEN** o Collector é reconfigurado para exportar para um backend diferente do atual (ex.: de Grafana Tempo/Loki para Elasticsearch/Kibana)
- **THEN** nenhuma mudança é necessária no código ou na configuração do portal e do broker

#### Scenario: Collector não configurado
- **WHEN** o endpoint do Collector não está definido
- **THEN** o SDK de telemetria permanece no-op, como já ocorre hoje sem endpoint configurado

#### Scenario: Métricas seguem o mesmo caminho
- **WHEN** o endpoint de métricas está configurado
- **THEN** as métricas do portal e do broker vão ao mesmo Collector que recebe traços e logs, e a troca de backend continua sem exigir mudança no portal ou no broker
