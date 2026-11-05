# agent-sandbox Specification

## Purpose

Confina o processo do agente e toda a árvore de processos que ele gerar a um conjunto de caminhos e syscalls declarados no perfil do agente, auto-imposto pelo supervisor do container antes de executar o agente, sem depender de nenhum componente externo ou privilégio no host.

## Requirements

### Requirement: Confinamento auto-imposto antes de executar o agente
O supervisor do container SHALL instalar um filtro de syscalls e um conjunto de regras de acesso a caminhos antes de dar `exec` no comando do agente declarado pelo perfil, de modo que o confinamento esteja em vigor antes de qualquer código do agente correr.

#### Scenario: Confinamento em vigor antes do primeiro código do agente
- **WHEN** o container de um sistema inicia e o supervisor sobe o agente
- **THEN** o filtro de syscalls e as regras de caminho já estão instalados no momento em que o comando do agente começa a executar

#### Scenario: Confinamento herdado por toda a árvore de processos
- **WHEN** o agente, já confinado, inicia um processo filho (como o próprio opencode, um shell ou um script escrito por ele)
- **THEN** o processo filho herda o mesmo filtro de syscalls e as mesmas regras de caminho, sem exceção

#### Scenario: Confinamento é irrevogável
- **WHEN** o agente ou qualquer processo filho tenta remover ou afrouxar o confinamento em vigor
- **THEN** a tentativa falha, porque nenhum processo confinado tem permissão de kernel para reverter as regras já instaladas

### Requirement: Política de acesso a caminhos derivada do perfil do agente
O supervisor SHALL derivar as regras de acesso a caminhos exclusivamente dos `readable_paths` e `writable_paths` declarados no perfil do agente em uso, liberando leitura e escrita apenas sob os caminhos graváveis do perfil, leitura e execução apenas sob os caminhos legíveis do perfil, e negando por padrão qualquer caminho fora dessa lista.

#### Scenario: Escrita fora dos caminhos graváveis é negada
- **WHEN** o agente confinado tenta escrever em um caminho que não está entre os `writable_paths` do seu perfil
- **THEN** a escrita é recusada pelo kernel, independentemente da identidade de execução do processo

#### Scenario: Leitura dentro dos caminhos declarados funciona normalmente
- **WHEN** o agente confinado lê ou executa um arquivo sob um caminho declarado em `readable_paths` ou `writable_paths` do seu perfil
- **THEN** a operação é permitida e se comporta como antes do confinamento

#### Scenario: Trabalho essencial do agente continua funcionando
- **WHEN** o agente confinado gera uma app, grava checkpoints git no workspace e o supervisor sobe a app gerada
- **THEN** o workspace permanece gravável, os checkpoints continuam sendo criados e a app atende na porta esperada, sem exigir ajuste manual às regras de caminho

### Requirement: Política de syscalls nega chamadas que desarmariam o confinamento
O supervisor SHALL negar por padrão, para o agente confinado e toda sua árvore de processos, o conjunto de syscalls que não servem ao trabalho de gerar e servir uma app e que, se permitidas, dariam ao agente meios de escapar do confinamento ou de obter visibilidade sobre o host além do seu workspace.

#### Scenario: Syscall de fuga do confinamento é negada
- **WHEN** o agente confinado ou um processo filho seu chama uma syscall do conjunto negado (como `ptrace`, `bpf`, `mount`, `setns`, `perf_event_open`, `process_vm_readv`, `process_vm_writev`, `unshare` com `CLONE_NEWUSER`, `pivot_root` ou `io_uring_setup`)
- **THEN** a chamada falha, e o processo que a fez não trava nem perde o restante da sua capacidade de operar

#### Scenario: Syscalls necessárias ao runtime do agente permanecem disponíveis
- **WHEN** o runtime do agente usa uma syscall necessária ao seu próprio funcionamento que não está no conjunto negado (como a usada para memória executável compatível com W^X)
- **THEN** a chamada é permitida e o agente continua operando normalmente

### Requirement: Resposta explícita quando o host não suporta o confinamento
O portal SHALL determinar, por host, se o confinamento de caminhos é suportado pelo kernel, e SHALL aplicar um comportamento explícito e documentado quando não é suportado, em vez de subir o agente silenciosamente sem o confinamento esperado.

#### Scenario: Host sem suporte em ambiente de produção
- **WHEN** um sistema é provisionado em um host de produção sem suporte ao confinamento de caminhos
- **THEN** o provisionamento falha de forma explícita e registrada, em vez de subir o container sem o confinamento

#### Scenario: Host sem suporte em ambiente de desenvolvimento
- **WHEN** um sistema é provisionado em um host de desenvolvimento sem suporte ao confinamento de caminhos
- **THEN** o container sobe sem o confinamento de caminhos, e essa degradação fica visível para quem provisionou, em vez de passar despercebida

#### Scenario: Confinamento de syscalls independe do suporte a caminhos
- **WHEN** o host não suporta o confinamento de caminhos mas suporta o filtro de syscalls
- **THEN** o filtro de syscalls é instalado mesmo assim, já que as duas camadas são independentes

### Requirement: Confinamento é transparente ao chat e ao gate de destrutivas
O confinamento do agente SHALL operar inteiramente dentro do container do sistema, sob o supervisor, sem alterar o comportamento observável do chat, da geração de apps ou do gate de operações destrutivas.

#### Scenario: Fluxo de geração e aprovação não muda
- **WHEN** um usuário interage com o chat de um sistema cujo container tem o confinamento instalado
- **THEN** o fluxo de geração de apps e os pedidos de aprovação do gate se comportam exatamente como em um sistema sem o confinamento
