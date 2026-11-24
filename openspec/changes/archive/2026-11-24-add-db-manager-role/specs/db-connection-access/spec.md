# Spec Delta

## Purpose

Define quem pode usar cada conexão do catálogo de bancos: a autorização por sistema dada por quem gere o catálogo, o teto de modo de acesso, a ativação pelo dono do sistema com alias próprio, a revogação imediata e os avisos ao dono.

## ADDED Requirements

### Requirement: Autorização de conexão por sistema
O portal SHALL permitir que quem gere o catálogo (DB Manager ou admin) autorize uma conexão do catálogo para um sistema, e SHALL manter no máximo uma autorização por par conexão e sistema. Um sistema SHALL NOT usar uma conexão sem autorização vigente.

#### Scenario: DB Manager autoriza conexão para um sistema
- **WHEN** um DB Manager autoriza a conexão `Vendas prod` para o sistema X
- **THEN** a conexão passa a aparecer como disponível na aba de conexões do sistema X, ainda inativa

#### Scenario: Mesma conexão autorizada para dois sistemas
- **WHEN** um DB Manager autoriza a mesma conexão para os sistemas X e Y
- **THEN** cada sistema tem a própria autorização, com teto e estado independentes

#### Scenario: Autorização duplicada é recusada
- **WHEN** um DB Manager tenta autorizar para o sistema X uma conexão que já está autorizada para X
- **THEN** o portal recusa informando que a autorização já existe

#### Scenario: Quem não gere o catálogo não autoriza
- **WHEN** um editor que não é DB Manager nem admin tenta autorizar uma conexão para o próprio sistema
- **THEN** o portal recusa com mensagem de permissão insuficiente

#### Scenario: DB Manager autoriza para sistema próprio
- **WHEN** um usuário que é editor e DB Manager autoriza uma conexão para um sistema do qual é dono
- **THEN** o portal permite a autorização

### Requirement: Sistemas visíveis ao autorizar
Ao autorizar, o portal SHALL oferecer a quem gere o catálogo a lista de todos os sistemas com nome, slug e dono, e SHALL NOT conceder por isso acesso ao chat, ao código, à app nem à auditoria de sistemas que essa pessoa não acessaria de outra forma.

#### Scenario: DB Manager escolhe um sistema alheio
- **WHEN** um DB Manager abre a autorização de uma conexão
- **THEN** vê todos os sistemas com nome, slug e dono, inclusive os que não são dele

#### Scenario: DB Manager não entra no sistema alheio
- **WHEN** um DB Manager que não é dono, admin nem membro de grupo vinculado tenta abrir a página do sistema X
- **THEN** o portal recusa o acesso, mesmo havendo conexões autorizadas por ele para X

### Requirement: Teto de modo de acesso por autorização
Cada autorização SHALL ter um teto de modo de acesso definido por quem gere o catálogo, entre `read_only`, `read_write` e `schema_admin`, nessa ordem crescente, com `read_write` como padrão. Quem gere o catálogo SHALL poder alterar o teto de uma autorização existente.

#### Scenario: Teto padrão
- **WHEN** um DB Manager autoriza uma conexão sem escolher o teto
- **THEN** a autorização fica com teto `read_write`

#### Scenario: Tetos diferentes para a mesma conexão
- **WHEN** um DB Manager autoriza a mesma conexão com teto `read_only` para o sistema X e `read_write` para o sistema Y
- **THEN** cada sistema fica limitado ao próprio teto

#### Scenario: DB Manager eleva o teto
- **WHEN** um DB Manager muda o teto do sistema X de `read_write` para `schema_admin`
- **THEN** o dono de X passa a poder ativar ou mudar a conexão para `schema_admin`, e o modo vigente não muda sozinho

### Requirement: Ativação pelo dono do sistema
O portal SHALL permitir que quem gerencia o sistema (dono ou admin) ative e desative cada conexão autorizada para ele. Somente conexões ativas SHALL ser entregues ao agente e à app gerada do sistema.

#### Scenario: Conexão autorizada e inativa não chega ao agente
- **WHEN** uma conexão está autorizada para o sistema X mas o dono não a ativou
- **THEN** o agente de X não tem ferramenta para esse banco e a app de X não recebe variável de ambiente para ele

#### Scenario: Dono ativa a conexão
- **WHEN** o dono do sistema X ativa uma conexão autorizada informando alias e modo
- **THEN** o agente e a app de X passam a receber essa conexão

#### Scenario: Dono desativa a conexão
- **WHEN** o dono do sistema X desativa uma conexão ativa
- **THEN** o agente e a app de X deixam de recebê-la, e a autorização continua disponível para reativação

#### Scenario: Quem não gerencia o sistema não ativa
- **WHEN** um membro de grupo vinculado ao sistema X, que não é dono nem admin, tenta ativar uma conexão
- **THEN** o portal recusa com mensagem de permissão insuficiente

### Requirement: Alias definido na ativação
Ao ativar uma conexão, quem gerencia o sistema SHALL informar um alias, que identifica a conexão para o agente e para a app daquele sistema. O alias SHALL ser único entre as conexões ativas do sistema e SHALL NOT mudar enquanto a conexão estiver ativa.

#### Scenario: Alias pré-preenchido na primeira ativação
- **WHEN** o dono abre a ativação de uma conexão nunca ativada no sistema
- **THEN** o campo de alias vem preenchido a partir do nome da conexão no catálogo, já no formato aceito (por exemplo, `Estoque legado` vira `estoque-legado`), e pode ser alterado

#### Scenario: Alias em uso é recusado
- **WHEN** o dono tenta ativar uma conexão com um alias que outra conexão ativa do mesmo sistema já usa, ou que geraria a mesma variável de ambiente
- **THEN** o portal recusa a ativação informando o conflito

#### Scenario: Alias inválido é recusado
- **WHEN** o dono informa um alias vazio ou com caracteres além de letras, dígitos, hífen e sublinhado
- **THEN** o portal recusa a ativação informando o formato aceito

#### Scenario: Alias não muda com a conexão ativa
- **WHEN** o dono tenta alterar o alias de uma conexão ativa
- **THEN** o portal não oferece nem aceita a alteração

#### Scenario: Reativação pode trocar o alias
- **WHEN** o dono reativa uma conexão que já esteve ativa no sistema
- **THEN** o campo de alias vem preenchido com o alias anterior e aceita um novo valor

#### Scenario: Renomear no catálogo não afeta o alias
- **WHEN** um DB Manager renomeia no catálogo uma conexão ativa no sistema X
- **THEN** o alias em X permanece o mesmo e a app de X continua recebendo a mesma variável de ambiente

### Requirement: Modo de acesso ativo limitado ao teto
Ao ativar uma conexão, e a qualquer momento enquanto ela estiver ativa, quem gerencia o sistema SHALL escolher o modo de acesso vigente, igual ou inferior ao teto da autorização. O portal SHALL recusar um modo acima do teto.

#### Scenario: Dono ativa abaixo do teto
- **WHEN** o teto é `read_write` e o dono ativa a conexão em `read_only`
- **THEN** a conexão fica ativa em `read_only`

#### Scenario: Modo acima do teto é recusado
- **WHEN** o teto é `read_write` e o dono tenta ativar ou mudar a conexão para `schema_admin`
- **THEN** o portal recusa informando o teto da autorização

#### Scenario: Dono rebaixa o modo
- **WHEN** o dono muda uma conexão ativa de `schema_admin` para `read_write`
- **THEN** o novo modo passa a valer para o agente e para a app do sistema

### Requirement: Indicação de DDL liberada
O portal SHALL destacar toda conexão ativa em modo `schema_admin` com a data desde a qual esse modo está em vigor, na aba de conexões do sistema e na lista de autorizações vista por quem gere o catálogo.

#### Scenario: Selo na página do sistema
- **WHEN** uma conexão do sistema X está ativa em `schema_admin` desde o dia 24
- **THEN** a aba de conexões de X mostra que a DDL está liberada desde o dia 24

#### Scenario: Selo para o DB Manager
- **WHEN** um DB Manager abre as autorizações de uma conexão ativa em `schema_admin` no sistema X
- **THEN** a autorização de X aparece destacada com a data desde a qual a DDL está liberada

#### Scenario: Selo some ao rebaixar
- **WHEN** o modo vigente deixa de ser `schema_admin`
- **THEN** o destaque deixa de aparecer nos dois lugares

### Requirement: Confirmação ao conceder schema_admin em conexão compartilhada
Quando quem gere o catálogo define o teto `schema_admin` para um sistema numa conexão que também está autorizada para outros sistemas, o portal SHALL listar esses outros sistemas e exigir confirmação antes de aplicar.

#### Scenario: Conexão compartilhada pede confirmação
- **WHEN** um DB Manager define o teto `schema_admin` para o sistema X numa conexão também autorizada para Y e Z
- **THEN** o portal mostra Y e Z como sistemas que usam o mesmo banco e só aplica após confirmação

#### Scenario: Conexão de um único sistema não pede confirmação
- **WHEN** um DB Manager define o teto `schema_admin` numa conexão autorizada apenas para o sistema X
- **THEN** o portal aplica o teto sem a confirmação de compartilhamento

### Requirement: Revogação imediata
O portal SHALL permitir que quem gere o catálogo revogue a autorização de um sistema a qualquer momento, e a revogação SHALL cessar na hora a entrega da conexão ao agente e à app daquele sistema, sem depender de ação do dono.

#### Scenario: Revogação de conexão ativa
- **WHEN** um DB Manager revoga a autorização de uma conexão ativa no sistema X
- **THEN** o agente e a app de X deixam de receber essa conexão imediatamente, e ela some das conexões disponíveis de X

#### Scenario: Revogação não afeta outros sistemas
- **WHEN** um DB Manager revoga a autorização do sistema X numa conexão também ativa no sistema Y
- **THEN** o sistema Y continua recebendo a conexão sem interrupção

#### Scenario: Revogação de conexão inativa
- **WHEN** um DB Manager revoga uma autorização que o dono nunca ativou
- **THEN** a conexão deixa de aparecer como disponível no sistema

### Requirement: Rebaixamento de teto com efeito imediato
Quando quem gere o catálogo rebaixa o teto de uma autorização para abaixo do modo vigente, o portal SHALL reduzir o modo vigente ao novo teto na hora.

#### Scenario: Teto rebaixado derruba o modo
- **WHEN** uma conexão está ativa em `schema_admin` no sistema X e um DB Manager rebaixa o teto para `read_write`
- **THEN** a conexão passa imediatamente a valer em `read_write` para o agente de X

#### Scenario: Teto rebaixado sem atingir o modo vigente
- **WHEN** o teto é `schema_admin`, a conexão está ativa em `read_only` e um DB Manager rebaixa o teto para `read_write`
- **THEN** o modo vigente continua `read_only`

### Requirement: Aviso ao dono sobre revogação e rebaixamento
Quando a revogação, o rebaixamento de teto ou a exclusão da conexão do catálogo alterar o que um sistema recebe, o portal SHALL exibir na aba de conexões desse sistema um aviso com o que mudou, a data e o autor, até que quem gerencia o sistema o dispense.

#### Scenario: Aviso de revogação
- **WHEN** um DB Manager revoga uma conexão que estava ativa no sistema X com o alias `vendas`
- **THEN** a aba de conexões de X mostra que a conexão `vendas` foi revogada, com data e autor

#### Scenario: Aviso de rebaixamento
- **WHEN** um DB Manager rebaixa o teto e o modo vigente no sistema X cai de `schema_admin` para `read_write`
- **THEN** a aba de conexões de X mostra o rebaixamento, com data e autor

#### Scenario: Dono dispensa o aviso
- **WHEN** quem gerencia o sistema dispensa um aviso
- **THEN** o aviso deixa de aparecer na aba de conexões

#### Scenario: Mudança sem efeito não gera aviso
- **WHEN** um DB Manager revoga uma autorização nunca ativada, ou rebaixa um teto sem reduzir o modo vigente
- **THEN** nenhum aviso é exibido ao dono
