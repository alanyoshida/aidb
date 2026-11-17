# portal-identity Specification

## Purpose

Controla quem entra no portal e o que cada usuário pode fazer: autenticação local por e-mail e senha, tipos globais de usuário (admin, editor, app_user) e grupos que concedem acesso a sistemas.

## Requirements

### Requirement: Autenticação por e-mail e senha
No modo `local`, o portal SHALL autenticar usuários com e-mail e senha locais, com senhas armazenadas apenas em forma de hash. No modo `oidc`, a autenticação dos usuários SHALL ser feita pelo IdP conforme a capability `oidc-authentication`, e e-mail e senha locais valem apenas para o admin break-glass.

#### Scenario: Login com credenciais válidas
- **WHEN** no modo `local` um usuário ativo informa e-mail e senha corretos
- **THEN** o portal inicia sua sessão e o leva à área autenticada

#### Scenario: Login com credenciais inválidas
- **WHEN** no modo `local` um usuário informa e-mail inexistente, senha errada ou conta desativada
- **THEN** o portal rejeita o login com mensagem genérica, sem revelar qual campo falhou

#### Scenario: Página de login no modo OIDC
- **WHEN** no modo `oidc` um usuário não autenticado acessa o portal
- **THEN** o portal oferece a entrada pelo IdP e não exibe formulário de e-mail e senha

### Requirement: Sessão autenticada e logout
O portal SHALL manter a sessão do usuário autenticado até o logout ou expiração.

#### Scenario: Acesso contínuo durante a sessão
- **WHEN** um usuário autenticado navega pelo portal dentro da validade da sessão
- **THEN** permanece autenticado sem novo login

#### Scenario: Logout
- **WHEN** o usuário encerra a sessão
- **THEN** requisições posteriores com aquela sessão são recusadas e exigem novo login

### Requirement: Tipos globais de usuário
O portal SHALL atribuir a cada usuário exatamente um tipo global — `admin`, `editor` ou `app_user` — que define suas capacidades no portal inteiro. No modo `local` o tipo é atribuído pelo admin; no modo `oidc` o tipo é derivado dos papéis do token conforme a capability `oidc-authentication`.

#### Scenario: Editor cria sistema
- **WHEN** um usuário do tipo `editor` solicita a criação de um sistema
- **THEN** o portal permite e o registra como dono do sistema criado

#### Scenario: app_user não cria sistema
- **WHEN** um usuário do tipo `app_user` tenta criar um sistema ou acessar o chat de geração
- **THEN** o portal recusa com mensagem de permissão insuficiente

#### Scenario: Admin tem acesso total
- **WHEN** um usuário do tipo `admin` acessa qualquer área administrativa ou sistema
- **THEN** o portal permite o acesso

#### Scenario: Tipo vem do IdP no modo OIDC
- **WHEN** no modo `oidc` um usuário entra com o papel `editor` no token
- **THEN** ele tem o tipo `editor` no portal, sem ação do admin

### Requirement: Administração de usuários pelo admin
No modo `local`, o portal SHALL restringir a gestão de usuários (criar, editar tipo, desativar) a administradores. No modo `oidc`, o portal SHALL NOT oferecer criação de usuários, edição de tipo nem desativação — essas decisões pertencem ao IdP — e a lista de usuários SHALL ser somente leitura.

#### Scenario: Admin cria usuário com tipo
- **WHEN** no modo `local` um admin cria um usuário informando e-mail, senha inicial e tipo
- **THEN** o usuário é criado com aquele tipo e pode autenticar-se

#### Scenario: Não-admin tenta gerenciar usuários
- **WHEN** um usuário `editor` ou `app_user` tenta criar ou alterar usuários
- **THEN** o portal recusa a operação

#### Scenario: Gestão de usuários indisponível no modo OIDC
- **WHEN** no modo `oidc` um admin abre a administração de usuários
- **THEN** vê os usuários que já entraram, com tipo e último login, sem ações de criar, alterar tipo ou desativar

### Requirement: Grupos concedem acesso a sistemas
O portal SHALL permitir que administradores criem grupos e vinculem grupos a sistemas, de modo que membros de um grupo vinculado podem acessar os sistemas do grupo conforme seu tipo global. No modo `local`, a pertença a grupos é definida pelo admin no portal; no modo `oidc`, a pertença vem do claim de grupos do token, casando pelo nome exato do grupo cadastrado, conforme a capability `oidc-authentication`.

#### Scenario: Membro de grupo acessa sistema vinculado
- **WHEN** um `app_user` pertence a um grupo vinculado ao sistema X
- **THEN** ele pode usar a app gerada do sistema X

#### Scenario: Usuário sem vínculo não vê o sistema
- **WHEN** um usuário não é dono, não é admin e não pertence a grupo vinculado ao sistema X
- **THEN** o sistema X não aparece em suas listas e o acesso direto é recusado

#### Scenario: Admin cadastra grupo com nome do IdP
- **WHEN** no modo `oidc` um admin cadastra o grupo `financeiro` e o vincula ao sistema X
- **THEN** usuários cujo token traz o grupo `financeiro` passam a acessar o sistema X

#### Scenario: Sugestão de nomes vistos
- **WHEN** no modo `oidc` um admin vai cadastrar um grupo
- **THEN** o portal sugere nomes de grupos já vistos em tokens que ainda não estão cadastrados e aceita também um nome nunca visto, avisando que nenhum usuário com esse grupo entrou ainda

### Requirement: Exclusão de usuário pelo admin
No modo `local`, o portal SHALL permitir que o admin exclua um usuário após confirmação, removendo seus vínculos de grupo e transferindo a posse dos sistemas dele conforme a capability system-management. No modo `oidc`, a exclusão de usuários pelo portal SHALL NOT estar disponível.

#### Scenario: Admin exclui usuário
- **WHEN** no modo `local` um admin confirma a exclusão de um usuário
- **THEN** o usuário é removido, seus vínculos de grupo são apagados e a posse de seus sistemas é transferida

#### Scenario: Histórico permanece após a exclusão
- **WHEN** um admin exclui um usuário que possui histórico (execuções, uso de tokens, checkpoints e decisões do gate)
- **THEN** o histórico permanece, atribuído ao e-mail do usuário excluído, sem depender da referência à tabela de usuários

#### Scenario: Exclusão indisponível no modo OIDC
- **WHEN** no modo `oidc` um admin consulta um usuário
- **THEN** não há ação de exclusão disponível

### Requirement: Gestão de grupos pelo admin
O portal SHALL permitir que o admin renomeie e exclua grupos e desvincule sistemas de um grupo, nos dois modos. Remover membros de um grupo SHALL estar disponível apenas no modo `local`; no modo `oidc` a lista de membros não é gerenciada pelo portal. Excluir um grupo remove seus vínculos sem excluir sistemas ou usuários. No modo `oidc`, renomear um grupo SHALL exibir aviso de que o novo nome precisa coincidir com o nome do grupo no IdP.

#### Scenario: Admin renomeia grupo
- **WHEN** um admin altera o nome de um grupo
- **THEN** o grupo passa a ter o novo nome

#### Scenario: Aviso ao renomear no modo OIDC
- **WHEN** no modo `oidc` um admin vai renomear um grupo
- **THEN** o portal avisa que usuários só casarão com o grupo se o novo nome for idêntico ao do IdP

#### Scenario: Admin remove membro
- **WHEN** no modo `local` um admin remove um usuário de um grupo
- **THEN** o usuário deixa de ser membro do grupo

#### Scenario: Admin desvincula sistema
- **WHEN** um admin desvincula um sistema de um grupo
- **THEN** os membros do grupo deixam de acessar aquele sistema

#### Scenario: Admin exclui grupo
- **WHEN** um admin confirma a exclusão de um grupo
- **THEN** o grupo e seus vínculos são removidos, preservando os sistemas e usuários

### Requirement: Modo de autenticação fixado na instalação
O portal SHALL operar em exatamente um modo de autenticação, `local` ou `oidc`, definido por configuração de implantação. O modo SHALL ser registrado no primeiro início do portal e o portal SHALL recusar-se a iniciar, com mensagem explicando a divergência, se o modo configurado for diferente do registrado. Trocar o modo de uma instalação existente não é suportado.

#### Scenario: Primeiro início registra o modo
- **WHEN** o portal inicia pela primeira vez com o modo `oidc`
- **THEN** o modo `oidc` fica registrado e o login passa a ser feito pelo IdP

#### Scenario: Modo divergente impede o início
- **WHEN** uma instalação registrada como `local` é iniciada com o modo `oidc`
- **THEN** o portal não inicia e informa que o modo configurado diverge do registrado na instalação

#### Scenario: Configuração OIDC incompleta
- **WHEN** o portal é iniciado no modo `oidc` sem emissor, client ou segredo do client configurados
- **THEN** o portal não inicia e informa qual configuração está faltando

### Requirement: Admin break-glass
O portal SHALL suportar um administrador de emergência (break-glass) definido exclusivamente pela configuração de implantação (e-mail e hash de senha), disponível nos dois modos de autenticação por uma rota de login local própria. O break-glass SHALL ter sempre o tipo `admin`, SHALL NOT pertencer a grupos e SHALL NOT poder ser editado, desativado ou excluído pela interface do portal. Sem a configuração, não há break-glass.

#### Scenario: Break-glass entra no modo OIDC
- **WHEN** no modo `oidc` o break-glass informa suas credenciais na rota de login local
- **THEN** ele entra como `admin`

#### Scenario: Break-glass removido da configuração
- **WHEN** a configuração do break-glass é removida e o portal é reiniciado
- **THEN** o login do break-glass deixa de ser aceito e suas sessões abertas são recusadas

#### Scenario: Break-glass não é gerenciável pela UI
- **WHEN** um admin tenta alterar o tipo, desativar ou excluir o break-glass pela interface
- **THEN** o portal recusa a operação

### Requirement: Proteções da sessão de emergência
O portal SHALL registrar na trilha de auditoria de gestão cada tentativa de login do break-glass, bem-sucedida ou não; SHALL exibir aviso permanente de sessão de emergência enquanto ele estiver logado; SHALL limitar a sessão do break-glass a no máximo 8 horas; e SHALL limitar por taxa as tentativas na rota de login local.

#### Scenario: Login de emergência auditado e sinalizado
- **WHEN** o break-glass entra com sucesso
- **THEN** a trilha de auditoria registra o login e a interface mostra o aviso de sessão de emergência em todas as páginas

#### Scenario: Break-glass com senha errada
- **WHEN** alguém informa o e-mail do break-glass com senha errada
- **THEN** o login é recusado com mensagem genérica e a tentativa é auditada

#### Scenario: Sessão de emergência expira
- **WHEN** passam 8 horas desde o login do break-glass
- **THEN** a sessão é encerrada e um novo login é exigido

#### Scenario: Excesso de tentativas
- **WHEN** a rota de login local recebe tentativas falhas em sequência acima do limite configurado
- **THEN** novas tentativas são recusadas temporariamente, mesmo com a senha correta

### Requirement: Retorno ao destino após o login
O portal SHALL, ao exigir login para uma página ou app do próprio portal, levar o usuário de volta a esse destino depois do login bem-sucedido, nos dois modos. Destinos fora do portal SHALL ser ignorados, levando o usuário à área autenticada.

#### Scenario: Volta à página pedida
- **WHEN** um usuário não autenticado abre uma página interna do portal, é levado ao login e entra
- **THEN** ele chega à página que tinha pedido

#### Scenario: Destino externo é ignorado
- **WHEN** o login é iniciado com destino apontando para outro site
- **THEN** depois de entrar o usuário é levado à área autenticada do portal, não ao outro site
