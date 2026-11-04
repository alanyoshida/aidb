# Spec Delta

## ADDED Requirements

### Requirement: Guidelines incluem instruções de formatação de artifacts visuais
As guidelines globais da plataforma SHALL incluir instruções que ensinam o agente a usar blocos especiais (```echart```, ```table```, ```html```) quando o editor solicitar visualizações, gráficos ou tabelas, de modo que o chat possa renderizá-los visualmente.

#### Scenario: Agente usa bloco echart ao ser pedido gráfico
- **WHEN** o editor pede ao agente "mostre um gráfico de vendas por mês"
- **THEN** o agente retorna uma resposta com um bloco ```echart``` contendo JSON de configuração válido para Apache ECharts

#### Scenario: Agente usa bloco table ao ser pedido tabela
- **WHEN** o editor pede ao agente "liste os clientes em uma tabela"
- **THEN** o agente retorna uma resposta com um bloco ```table``` contendo JSON array dos dados

#### Scenario: Agente usa texto simples quando não há dados visuais
- **WHEN** o editor faz um pedido que não envolve visualização de dados
- **THEN** o agente responde normalmente em texto, sem usar blocos de artifact desnecessariamente
