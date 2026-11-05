# Proposal

## Why

O container de cada sistema roda o agente como **root, com todas as capabilities padrão do Docker**, o que dá ao agente — um principal semi-confiável, exposto a prompt injection pelo conteúdo das tabelas que ele lê — muito mais poder sobre o container do que o trabalho dele exige. Ao mesmo tempo, a definição do runtime do agente está **espalhada e fixada em opencode**: o comando fica num constante do supervisor, o config é escrito por uma função específica do opencode e o nome da env de credencial vem do catálogo de provedores. Trocar o opencode por outro agente, ou rodar um segundo, exigiria mexer em provisionamento e supervisor.

Esta é a etapa 1 de [`docs/roadmap-confinamento-do-agente.md`](../../../docs/roadmap-confinamento-do-agente.md): ela não confina o agente ainda, mas estabelece as duas bases que todas as etapas seguintes leem — a identidade de execução reduzida e a definição declarativa do runtime.

## What Changes

- **Perfil de runtime do agente**: cada sistema passa a ter um perfil nomeado que define, num só lugar, o comando do agente, o diretório de trabalho, o arquivo de configuração, o nome da env pela qual o agente recebe sua credencial de LLM, a porta do harness e os caminhos que o agente precisa ler e escrever. O perfil é a fonte única consultada pelo provisionamento e pelo supervisor.
- **Supervisor dirigido pelo perfil**: o supervisor deixa de carregar um comando fixo de agente e passa a ler o perfil entregue pelo portal no diretório de configuração que já é montado somente-leitura.
- **Identidade de execução reduzida**: containers de sistema novos sobem com usuário não-root, sem nenhuma capability (`cap_drop: ALL`), sem escalada de privilégio (`no-new-privileges`) e com teto de processos.
- **Imagem base preparada para não-root**: o agente deixa de ser instalado dentro de `/root` (inacessível a usuário não-root) e o container passa a ter um `HOME` gravável pelo usuário do agente.
- **Modo de execução fixado por sistema**: cada sistema registra, na criação, sob qual modo de execução seu container roda, e esse modo não muda depois. Sistemas criados antes desta mudança continuam rodando como hoje, sem migração de dono de workspace; apenas sistemas novos nascem com a identidade reduzida.

Explicitamente **fora de escopo** (etapas seguintes do roadmap): rootfs somente-leitura, seccomp e Landlock, qualquer proxy de banco ou de inferência, e o segundo perfil de agente. Esta change não altera nenhum comportamento visível no chat, na app gerada ou no gate de destrutivas.

## Capabilities

### New Capabilities
- `agent-runtime`: define qual agente roda no container de um sistema e como esse runtime é descrito — comando, configuração, credencial e caminhos — de forma que a plataforma possa passar a suportar mais de um agente sem alterar provisionamento, supervisão ou as camadas de segurança construídas sobre ele

### Modified Capabilities
- `container-lifecycle`: ganha dois requisitos — identidade de execução reduzida do container (não-root, sem capabilities, sem escalada de privilégio) e modo de execução fixado por sistema, que preserva os sistemas existentes na reconciliação e no reprovisionamento — e o requisito de limites padrão passa a incluir teto de processos

## Impact

- `base-image/Dockerfile`: usuário não-root, instalação do agente fora de `/root`, `HOME` gravável
- `base-image/afsupervisor/supervisor.py`: `HARNESS_CMD` sai do módulo; o comando e o diretório de trabalho do agente vêm do perfil
- `portal/appaiforge/`: registro de perfis de agente; `provisioning.py` passa a escrever o perfil junto do config do agente e a aplicar usuário, `cap_drop`, `no-new-privileges` e teto de processos conforme o modo do sistema
- `portal/appaiforge/models.py` + migração Alembic: campo de modo de execução por sistema
- `portal/tests/`: unitários do registro de perfis e do supervisor dirigido por perfil; integração verificando a identidade de execução do container criado
- Sem mudança de API, de dependências ou de interface do usuário
