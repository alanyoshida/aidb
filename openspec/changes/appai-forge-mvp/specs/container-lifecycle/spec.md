# Spec Delta

## Purpose

Define o ciclo de vida do container de cada sistema: criação no provisionamento, limites de recursos, permanência ativa com reconciliação, e o destino do container e do workspace quando o sistema é desativado ou excluído.

## ADDED Requirements

### Requirement: Um container por sistema
O portal SHALL provisionar exatamente um container por sistema a partir da imagem base da plataforma, com volume de workspace persistente e rede interna própria, no momento da criação do sistema.

#### Scenario: Criação de sistema dispara container
- **WHEN** um sistema é criado e o provisionamento conclui
- **THEN** existe um container ativo dedicado a ele com workspace persistente

#### Scenario: Container preserva código entre reinícios
- **WHEN** o container de um sistema é reiniciado
- **THEN** o código gerado no workspace permanece intacto

### Requirement: Limites de recursos padrão
O portal SHALL aplicar a cada container de sistema os limites padrão configurados (CPUs, memória e disco) e impedir a criação que exceda a quantidade máxima de sistemas simultâneos configurada.

#### Scenario: Limites aplicados
- **WHEN** um container de sistema é criado
- **THEN** ele fica sujeito aos limites de CPU, memória e disco padrão da plataforma

#### Scenario: Teto de simultâneos atingido
- **WHEN** a criação de um novo sistema excederia o máximo de containers simultâneos
- **THEN** o portal informa a limitação e não provisiona até haver capacidade

### Requirement: Containers ativos e reconciliados
O portal SHALL manter os containers de sistemas sempre ativos com política de reinício automático, e ao iniciar (ou periodicamente) reconciliar o estado real dos containers com o estado registrado.

#### Scenario: Reinício do host
- **WHEN** o host reinicia
- **THEN** os containers de sistemas voltam a ficar ativos automaticamente

#### Scenario: Reconciliação corrige divergência
- **WHEN** o portal detecta um container ausente para um sistema ativo
- **THEN** o container é recriado com a mesma configuração e o workspace existente

### Requirement: Arquivamento e exclusão de sistema
O portal SHALL permitir que o dono arquive seu sistema — desativando acessos e o container, preservando o workspace — e que somente administradores executem a exclusão definitiva, removendo container e workspace.

#### Scenario: Dono arquiva sistema
- **WHEN** o dono arquiva um sistema
- **THEN** o container para, o sistema sai das listas de acesso e o workspace permanece guardado

#### Scenario: Admin exclui definitivamente
- **WHEN** um admin exclui um sistema arquivado
- **THEN** container e workspace são removidos permanentemente
