# 0018 — Perfil de runtime do agente e identidade de execução reduzida

* Status: aceito
* Data: 2026-11-04
* Decidida em: change `agent-runtime-profile-and-hardening` (design D1–D7)
* Relacionada: [0003](0003-container-por-sistema-com-supervisor-pid1.md), [0004](0004-opencode-serve-atras-de-adapter-com-fila-no-portal.md), [0013](0013-containers-sempre-ativos-com-reconciliacao.md)

## Contexto

O container de cada sistema roda o agente como root, com todas as capabilities padrão do Docker — mais poder sobre o container do que o trabalho do agente exige, dado que ele é um principal semi-confiável exposto a prompt injection pelo conteúdo que lê via MCP. Ao mesmo tempo, a definição do runtime do agente está espalhada e fixada em opencode: o comando fica numa constante do supervisor (`HARNESS_CMD`), o config é escrito por uma função específica do opencode, e o nome da env de credencial vem do catálogo de provedores. Trocar o opencode por outro agente, ou rodar um segundo, exigiria mexer em provisionamento e supervisor.

Esta é a etapa 1 de [`docs/roadmap-confinamento-do-agente.md`](../roadmap-confinamento-do-agente.md): não confina o agente ainda (seccomp e Landlock ficam para a etapa 2), mas estabelece as duas bases que as etapas seguintes leem.

## Decisão

**Perfil de runtime declarativo.** Cada sistema roda um agente identificado por um perfil nomeado (`portal/appaiforge/agent_profiles.py`, mesmo formato dos `PRESETS` do catálogo de provedores), que declara comando, diretório de trabalho, caminho do config, porta do harness, caminhos legíveis/graváveis, e o nome da env de credencial — literal ou `from_provider`, que delega ao catálogo (a env de credencial é uma interação agente × provedor, não propriedade fixa de um só). O portal serializa o perfil resolvido como JSON em `configs_dir/<slug>/agent-profile.json`, ao lado do `opencode.json`, e passa `AIDB_AGENT_PROFILE` apontando para ele no env do container — único ponto de entrada fixo do supervisor. O supervisor lê o comando, o cwd e a porta de dentro do arquivo; perfil ausente ou ilegível é falha explícita, nunca um agente embutido.

**Identidade de execução reduzida.** A imagem base relocou a instalação do opencode para fora de `/root` e passou a ter um usuário não-root (`agent`, uid/gid 1000) como padrão. Cada sistema fixa, na criação, um modo de execução imutável: `reduced` (novo padrão) sobe o container com esse usuário, `cap_drop: ALL` e `no-new-privileges`; `legacy` sobrescreve com `user="root"` explícito. O teto de processos (`pids_limit`) é configurável e aplicado aos dois modos, por ser limite de recurso, não de identidade.

**Sem migração de sistemas existentes.** Sistemas criados antes desta mudança ficam em `legacy` via `server_default` da migração e continuam acessando o workspace existente (dono root) sem nenhuma intervenção. Só sistemas novos nascem em `reduced`, com o workspace já criado com o dono do usuário do agente. Migrar um sistema `legacy` para `reduced` é ação futura, fora desta change.

## Alternativas consideradas

- **`chown` idempotente no provisionamento de todo sistema, sem campo de modo** — descartada: tocaria o dono dos arquivos de checkpoints git de sistemas em produção sem necessidade.
- **Perfil em YAML dentro da imagem** — perfil deixaria de poder variar por sistema, e a imagem passaria a ser o ponto de mudança para trocar de agente.
- **Perfil inteiro em variáveis de ambiente** — legível pelo agente via `/proc/self/environ` e desconfortável quando o perfil crescer; preferimos um arquivo no mount que já é somente-leitura.
- **Renomear o mount `/opencode-config`** — nenhum código passou a referenciá-lo como literal fora do supervisor (que o descobre pelo perfil), então o rename seria churn sem mudança de comportamento. Cabe na etapa em que o segundo perfil de agente entra.

## Consequências

- O supervisor (`afsupervisor`) não conhece mais nenhum agente por nome; registrar um perfil novo habilita um agente novo sem tocar em provisionamento, supervisor ou nas camadas de confinamento das etapas seguintes.
- A plataforma convive com dois modos de execução por tempo indeterminado; o modo é consultável por sistema, mas não há caminho automático de migração de `legacy` para `reduced`.
- O `HOME` do usuário do agente é uma camada gravável da própria imagem — o cache de pacotes do agente se perde na recriação do container, como já acontecia antes (sem regressão). Rootfs somente-leitura é decisão da etapa 2, informada pelo mapa de escrita que a execução real desta etapa produzir.
- Credenciais de provedor e de conexão continuam em env var do container — removê-las é o broker de inferência (etapa 3) e o proxy de banco (etapa 4) do roadmap, não esta change.
- O build da imagem base precisou de dois ajustes não relacionados a esta decisão (não documentados como ADR): o Debian do `python:3.12-slim` migrou de bookworm para trixie, descontinuando `libmysqlclient-dev` e exigindo `pkg-config` para o build do pacote python `mysqlclient` — corrigido no mesmo `Dockerfile` por ser pré-requisito de qualquer build futuro da imagem.
