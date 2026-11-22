# container-lifecycle Specification

## Purpose

Define o ciclo de vida do container de cada sistema: criação no provisionamento, limites de recursos, permanência ativa com reconciliação, e o destino do container e do workspace quando o sistema é desativado ou excluído.

## Requirements

### Requirement: Um container por sistema
O portal SHALL provisionar exatamente um container por sistema a partir da imagem base da plataforma, com volume de workspace persistente e rede interna própria, no momento da criação do sistema, usando o driver de provisionamento selecionado por configuração da plataforma (Docker ou Kubernetes).

#### Scenario: Criação de sistema dispara container
- **WHEN** um sistema é criado e o provisionamento conclui
- **THEN** existe um container ativo dedicado a ele com workspace persistente

#### Scenario: Container preserva código entre reinícios
- **WHEN** o container de um sistema é reiniciado
- **THEN** o código gerado no workspace permanece intacto

#### Scenario: Driver de provisionamento é escolha de configuração, não do sistema
- **WHEN** um sistema é criado, independentemente de qual driver de provisionamento está configurado na plataforma (Docker ou Kubernetes)
- **THEN** o sistema é provisionado por aquele driver, sem exigir nenhuma escolha do editor que cria o sistema

### Requirement: Limites de recursos padrão
O portal SHALL aplicar a cada container de sistema os limites padrão configurados (CPUs, memória e disco) e impedir a criação que exceda a quantidade máxima de sistemas simultâneos configurada. O limite de quantidade de processos SHALL ser aplicado sempre que o driver de provisionamento ativo garantir bloqueio rígido por container; nos drivers em que essa garantia não existir, o limite é melhor-esforço.

#### Scenario: Limites aplicados
- **WHEN** um container de sistema é criado
- **THEN** ele fica sujeito aos limites de CPU, memória e disco padrão da plataforma

#### Scenario: Teto de simultâneos atingido
- **WHEN** a criação de um novo sistema excederia o máximo de containers simultâneos
- **THEN** o portal informa a limitação e não provisiona até haver capacidade

#### Scenario: Quantidade de processos sem garantia sob driver sem bloqueio rígido
- **WHEN** o driver de provisionamento ativo não oferece bloqueio rígido de quantidade de processos por container
- **THEN** o portal continua configurando o limite padrão, mas não garante que ele seja respeitado com a mesma rigidez que um driver com bloqueio rígido oferece

### Requirement: Identidade de execução reduzida do container de sistema
O portal SHALL provisionar containers de sistema com identidade de execução reduzida: usuário não-root, sem nenhuma capability do kernel e sem possibilidade de escalada de privilégio, de modo que o agente opere com o menor poder suficiente para gerar e servir a app.

#### Scenario: Container novo roda sem root e sem capabilities
- **WHEN** um sistema novo é provisionado
- **THEN** o processo do agente no container roda com usuário não-root, sem capabilities do kernel e sem poder adquirir privilégio por binário com setuid

#### Scenario: Agente escreve no workspace e serve a app
- **WHEN** o agente gera a app de um sistema novo e o supervisor a sobe
- **THEN** o workspace é gravável pelo agente, a app atende na porta esperada e os checkpoints git do sistema continuam funcionando

#### Scenario: Identidade reduzida sobrevive à recriação
- **WHEN** o container de um sistema novo é recriado por reconciliação ou por reprovisionamento
- **THEN** ele volta com a mesma identidade de execução reduzida

### Requirement: Modo de execução fixado por sistema
O portal SHALL registrar, na criação de cada sistema, o modo de execução do seu container, e SHALL manter esse modo imutável pelo resto da vida do sistema. Sistemas criados antes da existência da identidade reduzida SHALL continuar rodando no modo com que foram criados, sem exigir migração de dono do workspace.

#### Scenario: Sistema existente preserva seu modo
- **WHEN** o container de um sistema criado antes desta mudança é recriado por reconciliação ou reprovisionamento
- **THEN** ele volta a subir no modo de execução original e o agente continua acessando o workspace existente

#### Scenario: Sistema novo nasce com identidade reduzida
- **WHEN** um sistema é criado após esta mudança
- **THEN** seu modo de execução é o reduzido e fica registrado no sistema

#### Scenario: Modo visível para o admin
- **WHEN** um admin consulta um sistema
- **THEN** o modo de execução do container daquele sistema é consultável, de modo que seja possível distinguir os sistemas que ainda rodam no modo antigo

### Requirement: Containers ativos e reconciliados
O portal SHALL manter os containers de sistemas sempre ativos com política de reinício automático e SHALL reconciliar o estado real dos containers com o estado registrado logo depois de iniciar e, a partir daí, periodicamente, num intervalo configurável pelo operador (com a opção de desligar só a reconciliação periódica, mantendo a da subida). A reconciliação SHALL rodar sem atrasar a subida do portal. Ela SHALL NOT agir sobre um sistema arquivado, em provisionamento, excluído ou que o portal esteja criando, recriando ou removendo naquele momento, e SHALL considerar o estado do sistema no momento em que age sobre ele, não o do início da passada. Uma falha inesperada ao reconciliar um sistema SHALL NOT impedir a reconciliação dos demais nem as passadas seguintes, e SHALL NOT mudar o estado registrado daquele sistema; a falha ao recriar um container SHALL deixar o sistema em erro com o motivo. Um sistema cujo container a reconciliação recria com sucesso SHALL voltar a ativo, sem mensagem de erro.

#### Scenario: Reinício do host
- **WHEN** o host reinicia
- **THEN** os containers de sistemas voltam a ficar ativos automaticamente

#### Scenario: Reconciliação corrige divergência
- **WHEN** o portal detecta um container ausente para um sistema ativo
- **THEN** o container é recriado com a mesma configuração e o workspace existente

#### Scenario: Reconciliação na subida do portal
- **WHEN** o portal inicia e um sistema ativo está sem container
- **THEN** o container é recriado sem intervenção do operador
- **AND** o portal passa a atender pedidos sem esperar a reconciliação terminar

#### Scenario: Reconciliação periódica
- **WHEN** o container de um sistema ativo é removido por fora com o portal já em execução
- **THEN** o container é recriado no máximo um intervalo de reconciliação depois

#### Scenario: Reconciliação periódica desligada
- **WHEN** o operador configura o intervalo de reconciliação como zero
- **THEN** o portal reconcilia só ao iniciar

#### Scenario: Sistema arquivado durante a passada não é recriado
- **WHEN** um sistema é arquivado depois de uma passada de reconciliação começar e antes de ela chegar a ele
- **THEN** a reconciliação não recria o container daquele sistema

#### Scenario: Operação do portal em andamento não é disputada
- **WHEN** a reconciliação chega a um sistema cujo container o portal está recriando ou removendo naquele momento
- **THEN** a reconciliação não age sobre aquele sistema nesta passada
- **AND** a próxima passada o reconcilia normalmente

#### Scenario: Falha inesperada num sistema não interrompe a passada
- **WHEN** a consulta ao estado real de um sistema falha por um erro inesperado, como o serviço de containers fora do ar
- **THEN** os demais sistemas são reconciliados na mesma passada
- **AND** o estado registrado do sistema que falhou não muda e a próxima passada tenta de novo

#### Scenario: Sistema recriado volta a ativo
- **WHEN** a reconciliação recria com sucesso o container de um sistema que estava em erro
- **THEN** o sistema fica ativo e sem mensagem de erro

### Requirement: Arquivamento e exclusão de sistema
O portal SHALL permitir que o dono arquive seu sistema — desativando acessos e o container, preservando o workspace — e que somente administradores executem a exclusão definitiva, removendo container, workspace e a config do sistema gerada pelo portal.

#### Scenario: Dono arquiva sistema
- **WHEN** o dono arquiva um sistema
- **THEN** o container para, o sistema sai das listas de acesso e o workspace permanece guardado

#### Scenario: Admin exclui definitivamente
- **WHEN** um admin exclui um sistema arquivado
- **THEN** container e workspace são removidos permanentemente

#### Scenario: Exclusão não deixa config órfã
- **WHEN** um admin exclui definitivamente um sistema
- **THEN** a pasta de config do sistema no portal (config do agente e perfil de runtime) também é removida
- **AND** outro sistema não é afetado
