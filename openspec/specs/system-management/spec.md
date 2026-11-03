# system-management Specification

## Purpose

Cobrim o cadastro e o acompanhamento de sistemas no portal: quem pode criá-los, o que define um sistema (slug, dono, provedor LLM) e como cada usuário enxerga os sistemas existentes.

## Requirements

### Requirement: Criação de sistema por editor
O portal SHALL permitir que usuários do tipo `editor` cadastrem sistemas com nome e slug único, tornando o criador o dono do sistema.

#### Scenario: Editor cadastra sistema com slug único
- **WHEN** um editor cadastra um sistema informando nome e slug ainda não utilizado
- **THEN** o sistema é criado no estado inicial de provisionamento e o criador consta como dono

#### Scenario: Slug duplicado é rejeitado
- **WHEN** um editor cadastra sistema com slug já existente
- **THEN** o portal recusa o cadastro e informa o conflito

### Requirement: Provedor de LLM configurável por sistema
O portal SHALL permitir escolher, no cadastro do sistema, o provedor e o modelo de LLM — dentre os provedores do catálogo — a ser usado pelo seu agente, com provedor padrão GLM quando não informado.

#### Scenario: Cadastro sem escolha de provedor
- **WHEN** um sistema é criado sem provedor informado
- **THEN** o sistema usa o provedor padrão GLM e o modelo padrão associado

#### Scenario: Dono altera provedor do sistema
- **WHEN** o dono altera o provedor/modelo de um sistema existente
- **THEN** as próximas conversas com o agente usam a nova configuração

#### Scenario: Provedor do catálogo disponível na escolha
- **WHEN** um editor cria um sistema ou edita o provedor de um sistema existente
- **THEN** as opções de provedor e modelo vêm do catálogo de provedores

### Requirement: Visibilidade de sistemas conforme permissão
O portal SHALL listar para cada usuário somente os sistemas dos quais ele é dono ou admin, e, para os demais, apenas os vinculados a grupos dos quais é membro.

#### Scenario: Dono vê seus sistemas
- **WHEN** um editor abre a lista de sistemas
- **THEN** aparecem os sistemas que criou e os de grupos aos quais pertence

#### Scenario: app_user vê apenas sistemas de seus grupos
- **WHEN** um `app_user` abre a lista de sistemas
- **THEN** aparecem somente os sistemas vinculados a grupos seus

### Requirement: Estado do sistema visível
O portal SHALL exibir para usuários com acesso o estado atual de cada sistema (por exemplo: provisionando, ativo, erro), incluindo o motivo quando em erro.

#### Scenario: Sistema em provisionamento
- **WHEN** o container de um sistema recém-criado ainda está sendo preparado
- **THEN** o sistema aparece como "provisionando" até ficar ativo

#### Scenario: Sistema com falha
- **WHEN** o provisionamento ou a execução de um sistema falha
- **THEN** o sistema aparece como "erro" com mensagem do motivo visível ao dono e a admins

### Requirement: Renomeação de sistema pelo dono
O portal SHALL permitir que o dono (ou um admin) altere o nome de exibição de um sistema existente, mantendo o slug imutável.

#### Scenario: Dono renomeia o sistema
- **WHEN** o dono altera o nome de um sistema existente
- **THEN** o novo nome passa a ser exibido em todo o portal e o slug (URL `/apps/<slug>`) permanece o mesmo

### Requirement: Transferência de posse ao excluir usuário
O portal SHALL transferir a posse dos sistemas de um usuário excluído para o administrador que executa a exclusão, de modo que todo sistema permaneça com um dono válido.

#### Scenario: Sistemas do usuário excluído são transferidos
- **WHEN** um admin exclui um usuário que possui sistemas
- **THEN** esses sistemas passam a ter o admin executor como dono
