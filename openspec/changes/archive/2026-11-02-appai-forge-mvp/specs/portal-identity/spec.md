# Spec Delta

## Purpose

Controla quem entra no portal e o que cada usuário pode fazer: autenticação local por e-mail e senha, tipos globais de usuário (admin, editor, app_user) e grupos que concedem acesso a sistemas.

## ADDED Requirements

### Requirement: Autenticação por e-mail e senha
O portal SHALL autenticar usuários com e-mail e senha locais, com senhas armazenadas apenas em forma de hash.

#### Scenario: Login com credenciais válidas
- **WHEN** um usuário ativo informa e-mail e senha corretos
- **THEN** o portal inicia sua sessão e o leva à área autenticada

#### Scenario: Login com credenciais inválidas
- **WHEN** um usuário informa e-mail inexistente, senha errada ou conta desativada
- **THEN** o portal rejeita o login com mensagem genérica, sem revelar qual campo falhou

### Requirement: Sessão autenticada e logout
O portal SHALL manter a sessão do usuário autenticado até o logout ou expiração.

#### Scenario: Acesso contínuo durante a sessão
- **WHEN** um usuário autenticado navega pelo portal dentro da validade da sessão
- **THEN** permanece autenticado sem novo login

#### Scenario: Logout
- **WHEN** o usuário encerra a sessão
- **THEN** requisições posteriores com aquela sessão são recusadas e exigem novo login

### Requirement: Tipos globais de usuário
O portal SHALL atribuir a cada usuário exatamente um tipo global — `admin`, `editor` ou `app_user` — que define suas capacidades no portal inteiro.

#### Scenario: Editor cria sistema
- **WHEN** um usuário do tipo `editor` solicita a criação de um sistema
- **THEN** o portal permite e o registra como dono do sistema criado

#### Scenario: app_user não cria sistema
- **WHEN** um usuário do tipo `app_user` tenta criar um sistema ou acessar o chat de geração
- **THEN** o portal recusa com mensagem de permissão insuficiente

#### Scenario: Admin tem acesso total
- **WHEN** um usuário do tipo `admin` acessa qualquer área administrativa ou sistema
- **THEN** o portal permite o acesso

### Requirement: Administração de usuários pelo admin
O portal SHALL restringir a gestão de usuários (criar, editar tipo, desativar) a administradores.

#### Scenario: Admin cria usuário com tipo
- **WHEN** um admin cria um usuário informando e-mail, senha inicial e tipo
- **THEN** o usuário é criado com aquele tipo e pode autenticar-se

#### Scenario: Não-admin tenta gerenciar usuários
- **WHEN** um usuário `editor` ou `app_user` tenta criar ou alterar usuários
- **THEN** o portal recusa a operação

### Requirement: Grupos concedem acesso a sistemas
O portal SHALL permitir que administradores criem grupos, adicionem usuários a eles e vinculem grupos a sistemas, de modo que membros de um grupo vinculado podem acessar os sistemas do grupo conforme seu tipo global.

#### Scenario: Membro de grupo acessa sistema vinculado
- **WHEN** um `app_user` pertence a um grupo vinculado ao sistema X
- **THEN** ele pode usar a app gerada do sistema X

#### Scenario: Usuário sem vínculo não vê o sistema
- **WHEN** um usuário não é dono, não é admin e não pertence a grupo vinculado ao sistema X
- **THEN** o sistema X não aparece em suas listas e o acesso direto é recusado
