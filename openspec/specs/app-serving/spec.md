# app-serving Specification

## Purpose

Define como a app gerada de cada sistema fica disponível dentro do portal: publicação em `/apps/{slug}` com reinício automático, controle de acesso pelos usuários do portal, propagação da identidade logada e sinalização de saúde.

## Requirements

### Requirement: Publicação da app em `/apps/{slug}`
O portal SHALL publicar a app gerada de cada sistema ativo no caminho `/apps/{slug}` assim que a app estiver sadia, mantendo o endereço estável enquanto o sistema existir.

#### Scenario: App no ar após geração
- **WHEN** o agente gera a primeira versão da app e ela fica sadia
- **THEN** a app passa a responder em `/apps/{slug}` do portal

#### Scenario: Reinício automático após edição
- **WHEN** o agente altera arquivos da app em uma execução
- **THEN** a app reinicia com o novo código e volta a responder no mesmo caminho

### Requirement: Acesso restrito a usuários com acesso ao sistema
O portal SHALL verificar, em cada requisição a `/apps/{slug}` (incluindo conexões WebSocket), se ela vem de uma sessão válida do portal com acesso ao sistema — dono, admins e membros de grupos vinculados —, nos dois modos de autenticação. Sem sessão válida, o usuário SHALL ser levado ao login e, depois de entrar, de volta ao endereço da app que pediu. Com sessão mas sem acesso, o portal SHALL recusar com mensagem de permissão insuficiente. Encerrar a sessão no portal ou perder o acesso ao sistema SHALL refletir-se na app já na requisição seguinte.

#### Scenario: app_user de grupo acessa a app
- **WHEN** um `app_user` membro de grupo vinculado abre `/apps/{slug}`
- **THEN** a app carrega com a identidade dele

#### Scenario: Usuário sem acesso é recusado
- **WHEN** um usuário logado sem vínculo com o sistema abre `/apps/{slug}`
- **THEN** o portal recusa com mensagem de permissão insuficiente

#### Scenario: Usuário não logado abre o link da app
- **WHEN** um usuário sem sessão abre `/apps/{slug}/relatorios`
- **THEN** é levado ao login e, depois de entrar com acesso ao sistema, chega a `/apps/{slug}/relatorios`

#### Scenario: Usuário logado entra direto
- **WHEN** um usuário já logado no portal, com acesso ao sistema, abre `/apps/{slug}` diretamente
- **THEN** a app carrega sem novo login e sem passar pela página do sistema no portal

#### Scenario: Logout alcança a app
- **WHEN** um usuário faz logout no portal e recarrega a app que estava aberta
- **THEN** a app não carrega e ele é levado ao login

#### Scenario: Acesso revogado alcança a app
- **WHEN** o grupo que dava acesso ao sistema é desvinculado ou deixa de constar para o usuário
- **THEN** a próxima requisição dele à app é recusada

### Requirement: Identidade do usuário propagada à app
O portal SHALL entregar à app gerada, em cada requisição autorizada, a identidade do usuário como um JWT assinado com segredo exclusivo daquele sistema e com audiência restrita àquela app, contendo identificador, e-mail, tipo global e grupos do usuário, com validade curta. A app SHALL validar assinatura, audiência e validade a cada requisição e tratar a identidade validada como o usuário da requisição, sem manter sessão própria que sobreviva ao fim da sessão no portal. Uma identidade emitida para uma app SHALL NOT ser aceita por outra app. Identidade enviada pelo cliente SHALL NOT chegar à app sem ter sido emitida pelo portal para aquela requisição.

#### Scenario: App identifica o usuário
- **WHEN** um usuário com acesso abre a app do sistema
- **THEN** a app o reconhece pelo identificador, tipo e grupos recebidos do portal

#### Scenario: Identidade de outra app
- **WHEN** chega à app do sistema X uma identidade emitida para o sistema Y
- **THEN** a app recusa a identidade

#### Scenario: Token de identidade inválido
- **WHEN** uma requisição chega à app com identidade inválida, expirada ou ausente
- **THEN** a app recusa a requisição

#### Scenario: Cliente tenta forjar a identidade
- **WHEN** um cliente envia à `/apps/{slug}` uma identidade forjada junto da requisição
- **THEN** a app recebe apenas a identidade emitida pelo portal para a sessão verificada, ou a requisição é recusada

### Requirement: Saúde da app visível no portal
O portal SHALL monitorar a saúde da app de cada sistema e exibir seu estado (rodando, fora do ar, com erro) na página do sistema, incluindo reinício com backoff em caso de falha.

#### Scenario: App fora do ar sinalizada
- **WHEN** a app de um sistema não responde ao health check
- **THEN** o sistema exibe estado de erro na página do sistema

#### Scenario: Recuperação automática
- **WHEN** a app falha e volta a responder após reinício com backoff
- **THEN** o estado do sistema volta a "rodando" sem intervenção
