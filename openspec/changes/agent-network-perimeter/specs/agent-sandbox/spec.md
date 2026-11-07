# Spec Delta

## ADDED Requirements

### Requirement: Confinamento de rede por porta TCP
O supervisor do container SHALL instalar, para o agente confinado em modo `sandboxed`, regras de rede que permitem conexão TCP de saída apenas às portas calculadas para o sistema, negando por padrão qualquer outra porta.

#### Scenario: Conexão a uma porta liberada funciona normalmente
- **WHEN** o agente confinado, ou um processo filho seu, abre uma conexão TCP de saída para uma porta que está na lista calculada para o sistema
- **THEN** a conexão é estabelecida normalmente, como se o confinamento de rede não existisse

#### Scenario: Conexão a uma porta não liberada é negada antes de alcançar a rede
- **WHEN** o agente confinado, ou um processo filho seu, tenta abrir uma conexão TCP de saída para uma porta que não está na lista calculada para o sistema — por exemplo, a porta real de um banco de dados, contornando o proxy de gate
- **THEN** a tentativa falha imediatamente por permissão negada, sem depender de a porta estar ou não alcançável na rede e sem travar o processo que tentou

#### Scenario: Lista de portas liberadas varia com as conexões do sistema
- **WHEN** um sistema tem mais de uma conexão de banco cadastrada, cada uma atrás de uma porta própria do proxy de gate
- **THEN** o agente desse sistema alcança todas as portas dos seus proxies de conexão, e nenhuma porta de proxy pertencente a outro sistema

#### Scenario: Porta do broker de inferência liberada quando o broker está habilitado
- **WHEN** o broker de inferência (etapa 3) está habilitado para o sistema
- **THEN** a porta do broker entra na lista de portas liberadas do agente, sem exigir qualquer outra mudança de configuração

#### Scenario: Confinamento de rede empilha sobre o de filesystem sem enfraquecê-lo
- **WHEN** o agente confinado já tem o confinamento de filesystem da etapa anterior em vigor e o supervisor instala, em seguida, o confinamento de rede
- **THEN** as regras de filesystem continuam valendo exatamente como antes, e as de rede passam a valer também — nenhuma das duas camadas enfraquece a outra

#### Scenario: Sistemas fora do modo sandboxed não são afetados
- **WHEN** um sistema está em modo `legacy` ou `reduced`
- **THEN** nenhuma regra de rede é instalada, e o comportamento de rede do container permanece o mesmo de antes desta mudança
