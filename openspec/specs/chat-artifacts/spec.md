# chat-artifacts Specification

## Purpose

Permite que o chat renderize conteúdo visual estruturado (gráficos, tabelas, HTML) embutido nas respostas do agente, detectando blocos especiais e exibindo-os como componentes interativos inline.

## Requirements

### Requirement: Renderização de gráficos ECharts inline
O portal SHALL detectar blocos ```echart``` nas respostas do agente e renderizá-los como gráficos Apache ECharts interativos diretamente no log de chat, sem que o editor precise navegar para outra página.

#### Scenario: Gráfico de barras exibido inline
- **WHEN** o agente retorna uma resposta contendo um bloco ```echart``` com JSON de configuração válido
- **THEN** o portal renderiza o gráfico interativo (bar, line, pie, scatter etc.) embutido na bolha de resposta do agente

#### Scenario: JSON inválido mostra cartão de erro
- **WHEN** o agente retorna um bloco ```echart``` com JSON malformado ou schema inválido
- **THEN** o portal exibe um cartão de aviso com a mensagem de erro e o conteúdo bruto colapsado, sem ocultar silenciosamente o bloco

### Requirement: Renderização de tabelas interativas inline
O portal SHALL detectar blocos ```table``` nas respostas do agente e renderizá-los como tabelas com filtro e ordenação, usando AG Grid.

#### Scenario: Tabela com filtro e sort
- **WHEN** o agente retorna um bloco ```table``` com JSON array de objetos válido
- **THEN** o portal renderiza uma tabela interativa com colunas derivadas das chaves do JSON, com filtro por coluna e ordenação clicável

#### Scenario: Array vazio exibe tabela vazia
- **WHEN** o agente retorna um bloco ```table``` com array JSON vazio (`[]`)
- **THEN** o portal exibe a tabela sem linhas, com as colunas visíveis se informadas, sem erro

#### Scenario: JSON inválido mostra cartão de erro
- **WHEN** o agente retorna um bloco ```table``` com conteúdo que não é JSON array válido
- **THEN** o portal exibe um cartão de aviso com a mensagem de erro e o conteúdo bruto colapsado

### Requirement: Renderização de HTML/SVG em sandbox inline
O portal SHALL detectar blocos ```html``` nas respostas do agente e renderizá-los em um iframe sandboxed, sem acesso a scripts externos ou ao DOM do portal.

#### Scenario: HTML renderizado isolado
- **WHEN** o agente retorna um bloco ```html``` com conteúdo HTML ou SVG
- **THEN** o portal renderiza o conteúdo em iframe com atributo sandbox, visível inline no chat, sem executar scripts que acessem recursos externos

#### Scenario: Conteúdo vazio não exibe iframe
- **WHEN** o agente retorna um bloco ```html``` vazio
- **THEN** o portal não renderiza nenhum componente para esse bloco

### Requirement: Texto fora de blocos preservado como markdown
O portal SHALL renderizar o texto fora dos blocos de artifact normalmente como markdown, preservando a leitura da resposta completa do agente intercalada com os componentes visuais.

#### Scenario: Resposta mista texto e artifact
- **WHEN** o agente retorna uma resposta com texto, um bloco ```echart``` e mais texto
- **THEN** o portal exibe o texto antes do bloco como markdown, o gráfico renderizado, e o texto após o bloco como markdown, nessa ordem
