# workspace-repository Specification

## Purpose

Define onde vive o repositório git de cada sistema e garante que o histórico de checkpoints fique fora do alcance do agente, de modo que nada escrito no workspace seja executado quando o portal opera esse repositório.

## Requirements

### Requirement: Repositório do sistema fora do alcance do agente
O portal SHALL manter o repositório git de cada sistema — objetos, referências, configuração e hooks — em local que o agente e a app gerada não conseguem ler nem escrever. O workspace SHALL ser apenas a árvore de trabalho desse repositório.

#### Scenario: Agente não alcança o histórico
- **WHEN** o agente ou a app gerada tenta ler ou alterar o repositório de checkpoints do sistema
- **THEN** não encontra esse repositório em nenhum caminho que consiga acessar

#### Scenario: Diretório `.git` no workspace não é o repositório
- **WHEN** existe um diretório `.git` dentro do workspace, criado pelo agente ou remanescente de versão anterior
- **THEN** o portal não o utiliza em nenhuma operação e seu conteúdo não entra em nenhum checkpoint

### Requirement: Nada controlado pelo workspace executa nas operações git
O portal SHALL executar as operações git de checkpoint, restauração e sincronização sem carregar hooks, configuração, filtros ou drivers definidos por conteúdo que o agente possa escrever.

#### Scenario: Hook plantado no workspace não executa
- **WHEN** o agente grava um hook git executável dentro do workspace e um checkpoint é criado em seguida
- **THEN** o checkpoint é criado e o hook não é executado

#### Scenario: Filtro declarado em atributos não executa
- **WHEN** o workspace contém um arquivo de atributos git que associa arquivos a um filtro ou driver de comando externo
- **THEN** o checkpoint é criado sem executar comando algum definido pelo workspace

#### Scenario: Configuração plantada é ignorada
- **WHEN** o agente grava configuração git dentro do workspace apontando para um comando externo
- **THEN** as operações git do portal não leem essa configuração

### Requirement: Arquivos escritos pelo portal permanecem editáveis pelo agente
Quando uma operação git do portal escreve arquivos no workspace (restauração de checkpoint ou sincronização), os arquivos resultantes SHALL permanecer legíveis e graváveis pelo agente e pela app gerada, em todos os modos de execução do sistema.

#### Scenario: Arquivo restaurado continua editável
- **WHEN** o dono restaura um checkpoint e em seguida pede ao agente uma alteração num arquivo restaurado
- **THEN** o agente consegue alterar o arquivo

### Requirement: Histórico existente preservado na mudança de local
Para sistemas criados antes desta capability, o portal SHALL levar o histórico de checkpoints para o novo local sem perder nenhum checkpoint registrado e sem alterar seus identificadores.

#### Scenario: Checkpoint antigo continua restaurável
- **WHEN** um sistema com checkpoints registrados antes da mudança tem um desses checkpoints restaurado depois dela
- **THEN** o workspace volta ao estado daquele checkpoint

#### Scenario: Histórico do workspace adulterado não substitui o registrado
- **WHEN** as referências do `.git` antigo no workspace apontam para um commit diferente do último checkpoint registrado pelo portal
- **THEN** o portal adota como ponto atual o último checkpoint que ele próprio registrou

### Requirement: Mesmo comportamento nos dois drivers de provisionamento
As garantias desta capability SHALL valer igualmente sob o driver Docker e sob o driver Kubernetes.

#### Scenario: Paridade entre drivers
- **WHEN** a mesma sequência de checkpoint, hook plantado e restauração é executada num sistema sob cada driver
- **THEN** o resultado observável é o mesmo nos dois

### Requirement: Exclusão definitiva remove o repositório
Na exclusão definitiva de um sistema, o portal SHALL remover também o repositório git do sistema e qualquer cópia auxiliar dele mantida pelo portal.

#### Scenario: Nada do histórico sobra após a exclusão
- **WHEN** um administrador exclui definitivamente um sistema
- **THEN** o repositório git do sistema e suas cópias auxiliares deixam de existir

#### Scenario: Arquivamento preserva o repositório
- **WHEN** o dono arquiva um sistema
- **THEN** o repositório git do sistema é preservado junto com o workspace
