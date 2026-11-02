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
O portal SHALL permitir o acesso à app publicada somente a usuários autenticados com acesso ao sistema: dono, admins, e membros de grupos vinculados.

#### Scenario: app_user de grupo acessa a app
- **WHEN** um `app_user` membro de grupo vinculado abre `/apps/{slug}`
- **THEN** a app carrega com a sessão dele

#### Scenario: Usuário sem acesso é recusado
- **WHEN** um usuário sem vínculo com o sistema abre `/apps/{slug}`
- **THEN** o portal recusa com mensagem de permissão insuficiente

### Requirement: Identidade do usuário propagada à app
O portal SHALL propagar à app gerada a identidade do usuário autenticado que a acessa, de forma assinada e à prova de falsificação, e a app SHALL tratá-la como sessão do usuário.

#### Scenario: App identifica o usuário
- **WHEN** um usuário com acesso abre a app do sistema
- **THEN** a app o reconhece pelo identificador e tipo recebidos do portal

#### Scenario: Token de identidade inválido
- **WHEN** uma requisição chega à app com token de identidade inválido ou expirado
- **THEN** a app recusa a sessão e o portal reautentica o usuário

### Requirement: Saúde da app visível no portal
O portal SHALL monitorar a saúde da app de cada sistema e exibir seu estado (rodando, fora do ar, com erro) na página do sistema, incluindo reinício com backoff em caso de falha.

#### Scenario: App fora do ar sinalizada
- **WHEN** a app de um sistema não responde ao health check
- **THEN** o sistema exibe estado de erro na página do sistema

#### Scenario: Recuperação automática
- **WHEN** a app falha e volta a responder após reinício com backoff
- **THEN** o estado do sistema volta a "rodando" sem intervenção
