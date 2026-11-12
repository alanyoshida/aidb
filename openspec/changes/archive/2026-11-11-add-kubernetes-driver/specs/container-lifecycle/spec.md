# Spec Delta

## MODIFIED Requirements

### Requirement: Um container por sistema
O portal SHALL provisionar exatamente um container por sistema a partir da imagem base da
plataforma, com volume de workspace persistente e rede interna própria, no momento da criação do
sistema, usando o driver de provisionamento selecionado por configuração da plataforma (Docker ou
Kubernetes).

#### Scenario: Criação de sistema dispara container
- **WHEN** um sistema é criado e o provisionamento conclui
- **THEN** existe um container ativo dedicado a ele com workspace persistente

#### Scenario: Container preserva código entre reinícios
- **WHEN** o container de um sistema é reiniciado
- **THEN** o código gerado no workspace permanece intacto

#### Scenario: Driver de provisionamento é escolha de configuração, não do sistema
- **WHEN** um sistema é criado, independentemente de qual driver de provisionamento está
  configurado na plataforma (Docker ou Kubernetes)
- **THEN** o sistema é provisionado por aquele driver, sem exigir nenhuma escolha do editor que
  cria o sistema

### Requirement: Limites de recursos padrão
O portal SHALL aplicar a cada container de sistema os limites padrão configurados (CPUs, memória
e disco) e impedir a criação que exceda a quantidade máxima de sistemas simultâneos configurada.
O limite de quantidade de processos SHALL ser aplicado sempre que o driver de provisionamento
ativo garantir bloqueio rígido por container; nos drivers em que essa garantia não existir, o
limite é melhor-esforço.

#### Scenario: Limites aplicados
- **WHEN** um container de sistema é criado
- **THEN** ele fica sujeito aos limites de CPU, memória e disco padrão da plataforma

#### Scenario: Teto de simultâneos atingido
- **WHEN** a criação de um novo sistema excederia o máximo de containers simultâneos
- **THEN** o portal informa a limitação e não provisiona até haver capacidade

#### Scenario: Quantidade de processos sem garantia sob driver sem bloqueio rígido
- **WHEN** o driver de provisionamento ativo não oferece bloqueio rígido de quantidade de
  processos por container
- **THEN** o portal continua configurando o limite padrão, mas não garante que ele seja respeitado
  com a mesma rigidez que um driver com bloqueio rígido oferece
