# Spec Delta

## MODIFIED Requirements

### Requirement: Debug log do chat reflete o rastreamento quando disponível
O Debug log de uma sessão de chat SHALL exibir a árvore de spans da execução correspondente sempre que houver spans persistidos para aquela execução, independente de qualquer backend de observabilidade externo estar configurado ou não. Quando não houver spans persistidos para aquela execução, o Debug log SHALL continuar exibindo o comportamento atual baseado em eventos em memória, sem regressão.

#### Scenario: Debug log com stack habilitado
- **WHEN** o usuário abre o Debug log de uma sessão cuja execução já aconteceu e produziu spans persistidos
- **THEN** o Debug log exibe a árvore de spans daquela execução, incluindo consultas ao banco, chamadas de ferramenta e chamadas de LLM associadas, lendo da tabela de spans em Postgres, sem consultar nenhum backend de observabilidade externo

#### Scenario: Debug log sem stack habilitado
- **WHEN** o usuário abre o Debug log de uma sessão cuja execução não produziu nenhum span persistido
- **THEN** o Debug log exibe os eventos em memória da execução, como hoje

## ADDED Requirements

### Requirement: Exportação de telemetria agnóstica de backend
A exportação de traços e logs do portal e do broker SHALL ser sempre direcionada a um endpoint de Collector fixo e configurável por variável de ambiente; a escolha de qual backend de observabilidade recebe esses dados (Grafana Tempo/Loki, Elastic, ou outro) SHALL ser determinada pela configuração do Collector, não pelo código ou pela configuração da aplicação.

#### Scenario: Troca de backend de observabilidade
- **WHEN** o Collector é reconfigurado para exportar para um backend diferente do atual (ex.: de Grafana Tempo/Loki para Elasticsearch/Kibana)
- **THEN** nenhuma mudança é necessária no código ou na configuração do portal e do broker

#### Scenario: Collector não configurado
- **WHEN** o endpoint do Collector não está definido
- **THEN** o SDK de telemetria permanece no-op, como já ocorre hoje sem endpoint configurado

### Requirement: Retenção dos spans persistidos para o Debug log
Os spans persistidos para uso do Debug log SHALL ser removidos automaticamente após um período de retenção configurável, para limitar o crescimento da tabela que os armazena.

#### Scenario: Span além do período de retenção
- **WHEN** um span persistido ultrapassa o período de retenção configurado
- **THEN** ele é removido pela limpeza automática, e deixa de aparecer no Debug log de execuções antigas
