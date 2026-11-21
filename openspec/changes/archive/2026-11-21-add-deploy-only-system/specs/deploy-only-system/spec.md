# Spec Delta

## Purpose

Permite que um portal de produção sirva sistemas que só implantam versões aprovadas de um repositório GitLab — sem agente, sem chat e sem credencial de LLM —, com verificação de que cada versão passou pela branch de destino, histórico de implantações e volta de versão.

## ADDED Requirements

### Requirement: Tipo do sistema escolhido na criação
O portal SHALL permitir escolher, ao criar um sistema, entre "com agente" e "só implantação", e SHALL manter o tipo imutável depois da criação. Sem escolha explícita, o tipo SHALL ser "com agente", preservando o comportamento atual.

#### Scenario: Criação de sistema só implantação
- **WHEN** um editor cria um sistema escolhendo "só implantação"
- **THEN** o sistema é criado com esse tipo e a página dele não oferece chat nem checkpoints

#### Scenario: Tipo padrão
- **WHEN** um editor cria um sistema sem escolher o tipo num portal de desenvolvimento
- **THEN** o sistema é criado como "com agente", como antes

#### Scenario: Tipo não muda
- **WHEN** quem gerencia um sistema tenta alterar o tipo dele
- **THEN** o portal não oferece essa alteração

### Requirement: Portal de produção só aceita sistemas só implantação
Num portal configurado com o papel de produção, o portal SHALL recusar criar sistema com agente e SHALL recusar provisionar qualquer sistema com agente, registrando o motivo no estado do sistema.

#### Scenario: Criação recusada
- **WHEN** num portal de produção um editor tenta criar um sistema com agente
- **THEN** a criação é recusada explicando que este portal só aceita sistemas só implantação

#### Scenario: Sistema com agente existente não sobe
- **WHEN** um portal configurado como produção encontra um sistema com agente ao provisionar ou reconciliar
- **THEN** o container desse sistema não é criado e o sistema fica em erro com o motivo

#### Scenario: Formulário de criação em produção
- **WHEN** um editor abre a criação de sistema num portal de produção
- **THEN** o tipo "só implantação" já vem escolhido e não há opção de provedor de LLM

### Requirement: Container sem agente
O container de um sistema só implantação SHALL NOT executar agente nem receber credencial ou token de LLM, e SHALL servir a app em `/apps/{slug}` com as mesmas regras de acesso, identidade e saúde dos demais sistemas.

#### Scenario: Nenhum agente nem credencial de LLM
- **WHEN** um sistema só implantação está ativo
- **THEN** nenhum processo de agente roda no container e nenhuma variável de credencial ou token de LLM existe nele

#### Scenario: App servida após implantação
- **WHEN** uma versão é implantada com sucesso
- **THEN** a app daquela versão responde em `/apps/{slug}` para quem tem acesso ao sistema

### Requirement: Repositório de origem com chave só de leitura
O portal SHALL vincular cada sistema só implantação a um repositório GitLab com chave de implantação própria, exibida para cadastro só de leitura, identidade do servidor confirmada por quem gerencia o sistema, branch de destino (padrão `main`) e padrão de tags (padrão `v*`). O portal SHALL NOT escrever nada no repositório.

#### Scenario: Padrões ao configurar
- **WHEN** o editor informa só o endereço do repositório
- **THEN** a branch de destino fica `main` e o padrão de tags fica `v*`

#### Scenario: Nada é escrito no repositório
- **WHEN** um sistema só implantação lista tags e implanta versões
- **THEN** nenhuma branch, tag ou commit do repositório remoto é criado ou alterado

### Requirement: Lista de versões disponíveis
O portal SHALL listar as tags do repositório que seguem o padrão do sistema, em ordem de versão da mais nova para a mais antiga, indicando a versão implantada e as já implantadas antes.

#### Scenario: Tags listadas
- **WHEN** o repositório tem as tags `v1.0.1`, `v1.0.10`, `v1.0.2` e `rascunho`
- **THEN** a lista mostra `v1.0.10`, `v1.0.2` e `v1.0.1`, nessa ordem, e não mostra `rascunho`

### Requirement: Implantação de tag verificada
O portal SHALL implantar uma tag somente se o commit dela estiver contido na branch de destino do repositório, e SHALL deixar o workspace com exatamente o conteúdo daquele commit.

#### Scenario: Tag aprovada implantada
- **WHEN** quem gerencia o sistema implanta uma tag cujo commit está na branch de destino
- **THEN** o workspace passa a ter o conteúdo daquele commit e a app reinicia nessa versão

#### Scenario: Tag fora da branch de destino recusada
- **WHEN** alguém tenta implantar uma tag cujo commit não está contido na branch de destino
- **THEN** a implantação é recusada explicando que a versão não passou pela branch de destino, e nada muda no workspace

#### Scenario: Tag movida depois de listada
- **WHEN** uma tag passa a apontar para outro commit entre a listagem e a implantação
- **THEN** o portal implanta e registra o commit que a tag aponta no momento da implantação, verificado contra a branch de destino

### Requirement: Dependências instaladas a partir do lock
Ao implantar uma versão, o container SHALL instalar as dependências declaradas no lock da app daquela versão antes de subir a app, e SHALL reaproveitar o ambiente quando o lock não mudou.

#### Scenario: Lock novo
- **WHEN** a versão implantada traz um lock de dependências diferente do anterior
- **THEN** as dependências são instaladas antes de a app subir

#### Scenario: Lock igual
- **WHEN** a versão implantada tem o mesmo lock da anterior
- **THEN** as dependências não são reinstaladas

### Requirement: Volta automática quando a versão não sobe
Se a app de uma versão recém-implantada não ficar saudável dentro do prazo configurado, o portal SHALL voltar o workspace à versão implantada anterior e SHALL registrar a implantação como falha com o motivo.

#### Scenario: Versão com falha
- **WHEN** a app de uma versão implantada não responde ao teste de saúde dentro do prazo
- **THEN** a versão anterior volta a ser servida e o histórico mostra a tentativa como falha

#### Scenario: Dependência que não instala
- **WHEN** a instalação das dependências de uma versão falha
- **THEN** a versão anterior continua servida e o histórico mostra a falha com o motivo

### Requirement: Histórico de implantações
O portal SHALL registrar cada implantação — tag, commit, quem ou o que a disparou (manual, consulta periódica ou webhook), quando e resultado — e SHALL exibir esse histórico e a versão atual na página do sistema e na auditoria.

#### Scenario: Implantação registrada
- **WHEN** uma implantação termina, com sucesso ou falha
- **THEN** o histórico mostra tag, commit, origem, momento e resultado

### Requirement: Voltar a uma versão anterior
O portal SHALL permitir que quem gerencia o sistema implante uma tag anterior pelo mesmo caminho de verificação da implantação normal.

#### Scenario: Rollback
- **WHEN** o editor implanta uma tag anterior à versão atual
- **THEN** a app passa a servir aquela versão e o histórico registra a implantação

### Requirement: Implantação automática só de versões novas
Com o modo automático ligado, o portal SHALL implantar a tag mais nova do padrão somente se ela nunca tiver sido implantada naquele sistema, com ou sem sucesso.

#### Scenario: Tag nova implantada sozinha
- **WHEN** o modo automático está ligado e aparece no repositório uma tag do padrão mais nova que todas as já implantadas
- **THEN** o portal a implanta sem ação humana e registra a origem como automática

#### Scenario: Rollback permanece
- **WHEN** o sistema está na v1.2 depois de alguém voltar manualmente da v1.3, e a v1.3 continua sendo a tag mais nova
- **THEN** a verificação automática não reimplanta a v1.3, e o sistema fica na v1.2 até surgir uma tag nova

#### Scenario: Tag que falhou não é repetida
- **WHEN** a implantação automática de uma tag falhou
- **THEN** as verificações seguintes não tentam implantá-la de novo

#### Scenario: Modo manual
- **WHEN** o modo automático está desligado
- **THEN** nenhuma tag é implantada sem ação de quem gerencia o sistema

### Requirement: Detecção por consulta periódica ou webhook
No modo automático, o portal SHALL detectar tags novas por consulta periódica ao repositório ou por webhook do GitLab, conforme escolhido no sistema. O webhook SHALL exigir o segredo do sistema e SHALL apenas disparar uma verificação do repositório, sem confiar em tag ou commit informados no corpo da chamada.

#### Scenario: Consulta periódica
- **WHEN** o sistema usa consulta periódica e surge uma tag nova
- **THEN** a tag é implantada até o fim do intervalo de consulta seguinte

#### Scenario: Webhook válido
- **WHEN** o GitLab chama o webhook do sistema com o segredo correto depois de criar uma tag
- **THEN** o portal verifica o repositório e implanta a tag nova, se houver

#### Scenario: Webhook com segredo errado
- **WHEN** o webhook é chamado sem o segredo do sistema ou com outro segredo
- **THEN** a chamada é recusada e nada é verificado nem implantado

#### Scenario: Corpo do webhook não é confiado
- **WHEN** o webhook chega com o segredo correto mas o corpo cita uma tag ou commit que não existem no repositório
- **THEN** nada é implantado além do que a verificação do repositório encontrar

### Requirement: Conexões exigidas pela versão
Antes de implantar uma versão, o portal SHALL ler o manifesto de conexões daquela versão e SHALL recusar a implantação quando alguma conexão exigida não estiver cadastrada no sistema com o mesmo nome, listando as que faltam.

#### Scenario: Conexão faltando
- **WHEN** o manifesto da versão exige a conexão `vendas` e o sistema não tem conexão com esse nome
- **THEN** a implantação é recusada listando `vendas` como faltante, e a versão atual continua servida

#### Scenario: Conexões completas
- **WHEN** todas as conexões do manifesto estão cadastradas no sistema
- **THEN** a implantação segue normalmente

#### Scenario: Versão sem manifesto
- **WHEN** a versão não tem manifesto de conexões
- **THEN** a implantação segue e o portal avisa que não pôde conferir as conexões
