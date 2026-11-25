# Spec Delta

## MODIFIED Requirements

### Requirement: Containers ativos e reconciliados
O portal SHALL manter os containers de sistemas sempre ativos com política de reinício automático e SHALL reconciliar o estado real dos containers com o estado registrado logo depois de iniciar e, a partir daí, periodicamente, num intervalo configurável pelo operador (com a opção de desligar só a reconciliação periódica, mantendo a da subida). A reconciliação SHALL rodar sem atrasar a subida do portal.

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

#### Scenario: Container parado é religado
- **WHEN** o container de um sistema existe mas está parado, por exemplo depois de um `docker stop` ou de ser morto pelo daemon
- **THEN** a reconciliação religa o mesmo container, sem recriá-lo nem trocar a imagem dele
- **AND** os sidecars do sistema são reiniciados depois do container do sistema, de modo que voltem a usar a rede dele

#### Scenario: Sistema com container religado volta a ativo
- **WHEN** a reconciliação religa o container de um sistema que estava em erro por app fora do ar
- **THEN** o sistema volta a ativo, sem mensagem de erro, assim que a app responder à checagem de saúde

#### Scenario: Sidecar parado é religado
- **WHEN** o container de um sistema está rodando e um sidecar dele existe mas está parado
- **THEN** a reconciliação religa o sidecar, sem recriá-lo e sem mexer no container do sistema
