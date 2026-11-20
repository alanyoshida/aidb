# Spec Delta

## Purpose

Liga o código gerado de um sistema a um repositório git remoto, para que cada alteração feita pelo chat chegue a uma branch de trabalho, receba o que humanos mergearem nela e possa ser promovida por merge request com revisão e pipelines.

## ADDED Requirements

### Requirement: Configuração do repositório remoto por sistema
O portal SHALL permitir que quem gerencia o sistema configure, numa aba "Repositório" da página do sistema, o endereço SSH do repositório remoto, a branch de trabalho (padrão `homolog`) e a branch de destino (padrão `main`). Sistemas sem repositório configurado SHALL continuar funcionando como antes.

#### Scenario: Aba visível para quem gerencia
- **WHEN** o dono do sistema ou um admin abre a página do sistema
- **THEN** a aba Repositório aparece junto das demais abas de gestão

#### Scenario: Aba ausente para quem não gerencia
- **WHEN** um usuário sem permissão de gestão sobre o sistema abre a página do sistema
- **THEN** a aba Repositório não aparece

#### Scenario: Branches com valor padrão
- **WHEN** o editor informa apenas o endereço do repositório
- **THEN** a branch de trabalho fica `homolog` e a de destino fica `main`

#### Scenario: Sistema sem repositório
- **WHEN** um sistema não tem repositório remoto configurado
- **THEN** checkpoints, restauração e chat funcionam sem nenhuma tentativa de envio

#### Scenario: Endereço que não é SSH
- **WHEN** o editor informa um endereço que não é um endereço git por SSH
- **THEN** o portal recusa a configuração explicando o formato aceito

### Requirement: Chave de implantação por sistema
O portal SHALL gerar um par de chaves SSH exclusivo para cada sistema, exibir a chave pública para cadastro no repositório remoto e guardar a chave privada cifrada, sem jamais exibi-la.

#### Scenario: Chave pública disponível para cópia
- **WHEN** o editor abre a aba Repositório de um sistema
- **THEN** vê a chave pública do sistema e consegue copiá-la

#### Scenario: Chaves diferentes por sistema
- **WHEN** dois sistemas têm repositório configurado
- **THEN** cada um exibe uma chave pública diferente

#### Scenario: Chave privada nunca exibida
- **WHEN** qualquer usuário, inclusive admin, consulta a configuração do repositório
- **THEN** a chave privada não aparece em nenhuma tela, resposta ou registro de auditoria

#### Scenario: Gerar nova chave
- **WHEN** o editor pede uma nova chave para o sistema
- **THEN** o portal passa a usar um par novo, exibe a nova chave pública e a anterior deixa de ser usada

### Requirement: Chave privada fora do container do sistema
A chave privada de implantação e o token de API do GitLab SHALL NOT ser entregues ao container do sistema por nenhum meio, e a configuração de um repositório remoto SHALL NOT ampliar os destinos de rede alcançáveis pelo agente.

#### Scenario: Chave ausente no container
- **WHEN** um sistema com repositório configurado já teve checkpoints enviados
- **THEN** a chave privada não existe no sistema de arquivos, nas variáveis de ambiente nem nos processos do container do sistema

#### Scenario: Token ausente no container
- **WHEN** um sistema com token de API configurado já teve uma promoção solicitada
- **THEN** o token não existe no sistema de arquivos, nas variáveis de ambiente nem nos processos do container do sistema

#### Scenario: Agente não alcança o servidor do repositório
- **WHEN** o agente de um sistema com repositório configurado tenta conectar diretamente ao servidor git remoto
- **THEN** a conexão é recusada pelo confinamento de rede, como seria antes da configuração

### Requirement: Token de API do GitLab por sistema
O portal SHALL permitir que quem gerencia o sistema cadastre, troque e remova um token de API do GitLab para o sistema, opcional, guardado cifrado e nunca exibido de volta, e SHALL permitir testar se o token alcança o projeto do repositório configurado. O endereço da API SHALL ser derivado do host do repositório, com possibilidade de informar outro.

#### Scenario: Token cadastrado
- **WHEN** o editor cadastra um token de API para o sistema
- **THEN** o portal confirma o cadastro e, em consultas posteriores, informa apenas que há um token configurado, sem exibi-lo

#### Scenario: Token testado
- **WHEN** o editor testa o token cadastrado
- **THEN** o portal informa se o token alcança o projeto do repositório e tem permissão para abrir merge request, sem alterar nada no remoto

#### Scenario: Token inválido
- **WHEN** o token cadastrado é recusado pelo GitLab
- **THEN** o teste informa que o token foi recusado, e a solicitação de promoção passa a mostrar o endereço de criação preenchido

#### Scenario: Endereço da API derivado do repositório
- **WHEN** o repositório é `git@gitlab.exemplo.com:time/app.git` e o editor não informa endereço de API
- **THEN** o portal usa `https://gitlab.exemplo.com` como endereço da API

### Requirement: Identidade do servidor remoto confirmada
O portal SHALL apresentar a impressão digital da chave do servidor remoto para confirmação de quem gerencia o sistema antes do primeiro uso, e SHALL recusar qualquer operação quando o servidor apresentar chave diferente da confirmada.

#### Scenario: Confirmação no primeiro uso
- **WHEN** o editor testa a conexão com um servidor ainda não confirmado
- **THEN** o portal mostra a impressão digital da chave do servidor e só prossegue depois da confirmação

#### Scenario: Chave do servidor mudou
- **WHEN** o servidor passa a apresentar chave diferente da confirmada
- **THEN** o portal não envia nem recebe nada, marca o repositório em erro e explica que a identidade do servidor mudou

### Requirement: Teste de conexão
O portal SHALL permitir testar o acesso ao repositório remoto com a chave do sistema, informando sucesso ou o motivo da falha, sem alterar o repositório remoto nem o workspace.

#### Scenario: Chave ainda não cadastrada no remoto
- **WHEN** o editor testa a conexão antes de cadastrar a chave pública no repositório remoto
- **THEN** o portal informa que o acesso foi negado e orienta a cadastrar a chave

#### Scenario: Conexão válida
- **WHEN** a chave está cadastrada com permissão de escrita e o editor testa a conexão
- **THEN** o portal informa sucesso e nada é alterado no remoto nem no workspace

### Requirement: Vínculo inicial com o repositório remoto
Ao ativar o repositório de um sistema, o portal SHALL publicar o histórico de checkpoints existente na branch de trabalho quando ela ainda não existir, e SHALL recusar o vínculo quando a branch de trabalho remota tiver histórico sem relação com o do sistema.

#### Scenario: Repositório remoto vazio
- **WHEN** o editor ativa o repositório apontando para um remoto sem a branch de trabalho
- **THEN** a branch de trabalho é criada no remoto com os checkpoints do sistema

#### Scenario: Branch de trabalho com histórico não relacionado
- **WHEN** a branch de trabalho já existe no remoto com histórico que não compartilha origem com o do sistema
- **THEN** o portal recusa o vínculo, explica o motivo e não altera o remoto nem o workspace

### Requirement: Envio de cada checkpoint à branch de trabalho
O portal SHALL enviar à branch de trabalho do repositório remoto todo checkpoint criado num sistema com repositório ativo — de execução do agente, manual ou de restauração — preservando o editor como autor, e SHALL NOT reescrever o histórico já publicado.

#### Scenario: Alteração pelo chat chega ao remoto
- **WHEN** uma execução do agente termina com sucesso num sistema com repositório ativo
- **THEN** o commit do checkpoint aparece na branch de trabalho do remoto com o editor como autor

#### Scenario: Restauração também é enviada
- **WHEN** o dono restaura um checkpoint anterior
- **THEN** o checkpoint de restauração aparece na branch de trabalho do remoto e os commits anteriores continuam lá

#### Scenario: Histórico publicado não é reescrito
- **WHEN** o portal envia checkpoints ao remoto
- **THEN** nenhum commit já presente na branch de trabalho remota é removido ou substituído

### Requirement: Falha de envio não invalida o checkpoint
Quando o envio ao remoto falha, o portal SHALL manter o checkpoint e o resultado da execução, marcar o repositório como "envio pendente" com o motivo, tentar de novo no checkpoint seguinte e oferecer o reenvio sob demanda.

#### Scenario: Remoto fora do ar
- **WHEN** uma execução termina com sucesso e o servidor remoto está inacessível
- **THEN** a execução é concluída normalmente, o checkpoint existe no histórico e a aba Repositório mostra "envio pendente" com o motivo

#### Scenario: Reenvio no checkpoint seguinte
- **WHEN** existe envio pendente e um novo checkpoint é criado com o remoto acessível
- **THEN** os dois checkpoints chegam ao remoto e o estado deixa de ser pendente

#### Scenario: Reenvio sob demanda
- **WHEN** o editor aciona "Enviar agora" com envio pendente e o remoto acessível
- **THEN** os checkpoints pendentes chegam ao remoto

### Requirement: Sincronização antes de cada execução
Antes de iniciar uma execução do agente num sistema com repositório ativo, o portal SHALL trazer para o workspace os commits novos da branch de trabalho remota e registrar o resultado como um checkpoint de origem remota. A indisponibilidade do remoto SHALL NOT impedir a execução.

#### Scenario: Merge request de humano chega ao workspace
- **WHEN** um merge request é mergeado na branch de trabalho remota e depois o editor envia um pedido no chat
- **THEN** a execução parte de um workspace que já contém as alterações mergeadas e a app reflete essas alterações

#### Scenario: Sincronização registrada no histórico
- **WHEN** a sincronização traz commits do remoto
- **THEN** o histórico de checkpoints mostra um ponto identificado como vindo do repositório remoto, restaurável como os demais

#### Scenario: Remoto inacessível antes da execução
- **WHEN** o remoto está inacessível quando o editor envia um pedido
- **THEN** a execução acontece sobre o estado local e o repositório fica marcado com o motivo da falha

#### Scenario: Sincronização sob demanda
- **WHEN** o editor aciona "Sincronizar agora" sem execução em andamento
- **THEN** o portal traz os commits novos da branch de trabalho e atualiza a app

### Requirement: Workspace estável durante a execução
O portal SHALL NOT alterar o workspace por sincronização enquanto uma execução do agente estiver em andamento naquele sistema.

#### Scenario: Merge remoto durante a execução
- **WHEN** um merge request é mergeado na branch de trabalho remota enquanto o agente está executando
- **THEN** os arquivos do workspace não mudam por causa disso até a execução terminar

#### Scenario: Sincronizar agora durante a execução
- **WHEN** o editor aciona "Sincronizar agora" com uma execução em andamento
- **THEN** o portal recusa a ação informando que há execução em andamento

### Requirement: Trabalho não salvo decidido pelo editor antes de sincronizar
Quando o workspace tem alterações ainda sem checkpoint e a branch de trabalho remota tem commits a trazer, o portal SHALL NOT sincronizar nem iniciar a execução do agente, e SHALL pedir a quem gerencia o sistema que salve essas alterações num checkpoint ou as descarte. O portal SHALL NOT salvar nem descartar por conta própria.

#### Scenario: Execução bloqueada por sobras de execução interrompida
- **WHEN** uma execução interrompida deixou arquivos alterados sem checkpoint, o remoto tem commits novos e o editor envia um pedido no chat
- **THEN** o agente não é acionado, o workspace não muda, e o chat informa que é preciso salvar ou descartar as alterações não salvas antes de continuar

#### Scenario: Editor salva e continua
- **WHEN** o editor escolhe salvar as alterações não salvas
- **THEN** elas viram um checkpoint, a sincronização acontece e o próximo pedido no chat é executado

#### Scenario: Editor descarta e continua
- **WHEN** o editor confirma o descarte das alterações não salvas
- **THEN** o workspace volta ao último checkpoint, a sincronização acontece e o próximo pedido no chat é executado

#### Scenario: Sem commits a trazer, nada é bloqueado
- **WHEN** há alterações sem checkpoint e a branch de trabalho remota não tem commits novos
- **THEN** a execução acontece normalmente, como num sistema sem repositório

#### Scenario: Sincronizar agora com alterações não salvas
- **WHEN** o editor aciona "Sincronizar agora" com alterações sem checkpoint e commits a trazer
- **THEN** o portal não sincroniza e apresenta a mesma escolha entre salvar e descartar

### Requirement: Estado divergente em caso de conflito
Quando os commits vindos do remoto conflitam com checkpoints locais ainda não enviados, o portal SHALL deixar o workspace no estado local, marcar o sistema como "divergente", listar os arquivos em conflito e suspender os envios até a resolução. O chat SHALL continuar disponível.

#### Scenario: Conflito detectado
- **WHEN** um merge feito no remoto durante uma execução altera as mesmas linhas que a execução alterou
- **THEN** o checkpoint local é mantido, o workspace não contém marcas de conflito, e a aba Repositório mostra "divergente" com a lista de arquivos em conflito

#### Scenario: Envios suspensos
- **WHEN** o sistema está divergente e um novo checkpoint é criado
- **THEN** o checkpoint é registrado localmente e nada é enviado ao remoto

#### Scenario: Alterações sem conflito são combinadas
- **WHEN** o remoto e o local têm commits novos que alteram arquivos ou trechos diferentes
- **THEN** o portal combina os dois sem intervenção, envia o resultado e o sistema não fica divergente

### Requirement: Resolução de divergência por ação explícita
O portal SHALL levar o conflito para os arquivos do workspace somente por ação explícita de quem gerencia o sistema, e SHALL concluir a resolução no checkpoint seguinte apenas quando nenhum arquivo em conflito ainda contiver marcas de conflito.

#### Scenario: Conflito levado ao workspace
- **WHEN** o editor aciona "Resolver no workspace" num sistema divergente
- **THEN** os arquivos em conflito passam a conter as duas versões marcadas, para o agente ou o editor resolverem pelo chat

#### Scenario: Resolução concluída
- **WHEN** os arquivos em conflito já não contêm marcas e um checkpoint é criado
- **THEN** o histórico local e o remoto são unidos, o resultado é enviado e o sistema deixa de estar divergente

#### Scenario: Resolução incompleta
- **WHEN** um checkpoint é criado e algum arquivo em conflito ainda contém marcas
- **THEN** o sistema continua divergente, nada é enviado e o portal indica quais arquivos faltam resolver

#### Scenario: Desistir da resolução
- **WHEN** o editor cancela a resolução em andamento
- **THEN** o workspace volta ao estado local anterior à ação e o sistema continua divergente

### Requirement: Adotar a versão do remoto num sistema divergente
O portal SHALL permitir que quem gerencia um sistema divergente adote a versão da branch de trabalho remota, mediante confirmação que liste os checkpoints locais não enviados. Após a ação, o workspace SHALL refletir o remoto, os checkpoints deixados de lado SHALL continuar restauráveis e nada SHALL ser alterado no repositório remoto.

#### Scenario: Remoto adotado
- **WHEN** o editor confirma "Adotar a versão do remoto" num sistema divergente
- **THEN** o workspace passa a ter o conteúdo da branch de trabalho remota, a app reflete esse conteúdo e o sistema deixa de estar divergente

#### Scenario: Confirmação mostra o que fica de lado
- **WHEN** o editor aciona "Adotar a versão do remoto"
- **THEN** o portal lista os checkpoints locais não enviados e só prossegue depois da confirmação

#### Scenario: Checkpoint deixado de lado continua restaurável
- **WHEN** o editor restaura, depois da adoção, um checkpoint local que não tinha sido enviado
- **THEN** o workspace volta ao estado daquele checkpoint, como um checkpoint novo sobre a versão do remoto

#### Scenario: Remoto não é alterado
- **WHEN** a versão do remoto é adotada
- **THEN** nenhum commit é enviado, removido ou substituído na branch de trabalho remota

#### Scenario: Ação indisponível fora da divergência
- **WHEN** o sistema não está divergente
- **THEN** a ação "Adotar a versão do remoto" não é oferecida

### Requirement: Solicitação de promoção por ação explícita
O portal SHALL abrir um merge request da branch de trabalho para a branch de destino somente quando quem gerencia o sistema aciona "Solicitar promoção", usando o token de API do sistema, e SHALL exibir o endereço do merge request. Sem token configurado, ou com o token recusado, o portal SHALL exibir o endereço de criação já preenchido com as duas branches.

#### Scenario: Promoção solicitada
- **WHEN** o editor aciona "Solicitar promoção" com todos os checkpoints enviados
- **THEN** existe no remoto um merge request da branch de trabalho para a branch de destino e o portal mostra o endereço dele

#### Scenario: Nenhum merge request automático
- **WHEN** checkpoints são enviados ao remoto sem que ninguém acione "Solicitar promoção"
- **THEN** nenhum merge request é aberto

#### Scenario: Merge request já aberto
- **WHEN** o editor aciona "Solicitar promoção" e já existe merge request aberto entre as duas branches
- **THEN** o portal mostra o endereço do merge request existente em vez de abrir outro

#### Scenario: Promoção sem token
- **WHEN** o editor aciona "Solicitar promoção" num sistema sem token de API
- **THEN** o portal mostra o endereço de criação do merge request já preenchido com as duas branches, e nada é aberto no remoto

#### Scenario: Promoção indisponível com pendência
- **WHEN** o sistema está divergente ou com envio pendente
- **THEN** o portal recusa a solicitação e explica o que precisa ser resolvido antes

### Requirement: Definição de pipeline protegida
O portal SHALL NOT enviar ao repositório remoto alterações originadas no workspace no arquivo `.gitlab-ci.yml` da raiz do repositório, e SHALL informar quem gerencia o sistema quando uma alteração desse tipo for deixada de fora.

#### Scenario: Agente cria o arquivo de pipeline
- **WHEN** o agente cria `.gitlab-ci.yml` na raiz do workspace e a execução termina com sucesso
- **THEN** o checkpoint enviado ao remoto não contém esse arquivo e o portal avisa que ele foi deixado de fora

#### Scenario: Agente altera arquivo de pipeline vindo do remoto
- **WHEN** `.gitlab-ci.yml` chegou ao workspace pela sincronização e o agente o altera
- **THEN** o checkpoint enviado mantém a versão do repositório e o portal avisa que a alteração foi deixada de fora

### Requirement: Estado do repositório visível e auditado
O portal SHALL exibir na aba Repositório o estado atual do vínculo — sincronizado, envio pendente, divergente ou erro, com o motivo — e SHALL registrar na auditoria do sistema a configuração, a troca de chave, o cadastro e a remoção do token de API, os envios, as sincronizações, as divergências e as solicitações de promoção.

#### Scenario: Estado sincronizado
- **WHEN** todos os checkpoints foram enviados e não há commits novos no remoto
- **THEN** a aba Repositório mostra o estado sincronizado e o último commit enviado

#### Scenario: Ações aparecem na auditoria
- **WHEN** o editor configura o repositório, cadastra o token de API e depois solicita uma promoção
- **THEN** a aba Auditoria do sistema mostra as três ações com autor e momento, sem o valor do token

### Requirement: Exclusão definitiva remove vínculo e chave
Na exclusão definitiva de um sistema, o portal SHALL remover a configuração do repositório remoto, a chave de implantação, o token de API e qualquer cópia do histórico mantida para o envio, sem alterar o repositório remoto.

#### Scenario: Nada do vínculo sobra após a exclusão
- **WHEN** um administrador exclui definitivamente um sistema com repositório configurado
- **THEN** a configuração, a chave privada, o token de API e as cópias auxiliares do histórico deixam de existir no portal, e o repositório remoto permanece intacto

### Requirement: Desvincular o repositório remoto
O portal SHALL permitir que quem gerencia o sistema desative o vínculo com o repositório remoto, interrompendo envios e sincronizações sem alterar o workspace, o histórico de checkpoints nem o repositório remoto.

#### Scenario: Vínculo desativado
- **WHEN** o editor desativa o repositório remoto de um sistema
- **THEN** os checkpoints seguintes não são enviados e o conteúdo já publicado no remoto permanece intacto
