# Design

## Context

Ver `proposal.md` — Why. O que molda a abordagem:

- O comando do agente é constante de módulo no supervisor (`HARNESS_CMD`) e o diretório de trabalho é o literal `/opencode-config`; o config é escrito por `write_opencode_config`, e o nome da env de credencial vem do catálogo de provedores (`env_name` em `PRESETS`).
- A imagem base instala o agente em `/root/.opencode/bin/opencode`, com symlink em `/usr/local/bin`. `/root` é inacessível a usuário não-root, então **não existe caminho para não-root sem relocar a instalação**.
- A imagem não define `HOME`; hoje o processo é root e usa `/root`. O agente escreve cache em `HOME` em runtime (pacotes de provedor do SDK) e o `uv` escreve o venv da app em `/workspace/app/.venv`.
- Os workspaces existentes no host têm dono root. A decisão do usuário foi **não migrar**: sistemas novos nascem com identidade reduzida, existentes seguem como estão.
- `configs_dir/<slug>` já é bind-mounted em `/opencode-config` **somente-leitura**, fora do workspace que o agente edita (ADR 0007 e a change `db-config-fora-do-workspace`). É o canal pronto para entregar o perfil.
- O catálogo de provedores (`PRESETS` em `services/catalog.py`) é o precedente do projeto para registro declarativo em Python.

## Goals / Non-Goals

**Goals:**
- O supervisor deixa de conhecer qualquer agente específico.
- O perfil é o único lugar onde se declara comando, cwd, config, credencial, porta e caminhos.
- Containers novos sobem sem root e sem capabilities, sem quebrar geração de app, checkpoints git nem a rota `/apps/{slug}`.
- Sistemas existentes continuam funcionando sem nenhuma intervenção operacional.

**Non-Goals:**
- Não aplica nenhum confinamento de kernel (seccomp, Landlock) nem rootfs somente-leitura — etapa 2 do roadmap.
- Não tira credencial nenhuma do container: as conexões e a chave do provedor seguem em env var. Etapas 3 e 4.
- Não adiciona um segundo perfil. Esta change prova a extensibilidade por teste, não por um agente real.
- Não renomeia o mount `/opencode-config` (ver Decisões).

## Decisions

### D1 — Registro Python no portal, perfil serializado como JSON no mount existente

O perfil é um registro em Python no portal, no formato do `PRESETS` do catálogo de provedores, e o portal serializa o perfil escolhido como JSON dentro de `configs_dir/<slug>/`, ao lado do config do agente que já é escrito ali.

*Por quê*: reusa o mount somente-leitura que já existe, sem volume nem canal novo; mantém o perfil versionado junto do código que o consome; e o JSON entregue ao container é derivado, não fonte — então pode ganhar campos sem migração de dados.

*Alternativas*: YAML dentro da imagem (perfil deixaria de poder variar por sistema, e a imagem passaria a ser o ponto de mudança); perfil inteiro em env vars (legível pelo agente via `/proc/self/environ` e desconfortável quando o perfil crescer).

### D2 — Um único ponto de entrada fixo: a env `AIDB_AGENT_PROFILE`

O perfil declara onde fica o config do agente, mas o supervisor precisa achar o **perfil** antes de saber qualquer coisa. Resolvemos com uma única env apontando para o arquivo do perfil; todo o resto vem de dentro dele.

*Por quê*: deixa de haver qualquer caminho literal de agente no supervisor, e o nome do mount deixa de ser load-bearing — o que torna o rename desnecessário (ver D6).

*Alternativa*: caminho fixo em constante no supervisor — reintroduziria exatamente o acoplamento que a change remove.

### D3 — `credential_env` aceita literal ou o marcador `from_provider`

O nome da env de credencial é uma interação **agente × provedor**, não propriedade de um só: no opencode ele é ditado pelo catálogo (`ZHIPU_API_KEY`, `ANTHROPIC_API_KEY`); num agente como o Claude Code seria fixo, qualquer que fosse o provedor por trás.

O campo do perfil aceita então um nome literal **ou** o marcador `from_provider`, que delega ao catálogo. O perfil do opencode usa `from_provider`, preservando exatamente o comportamento atual.

*Alternativa*: forçar literal no perfil — quebraria a escolha de provedor por sistema, que é requisito de `system-management`.

*Compatível com o híbrido da etapa 3*: o campo declara o **nome** da variável, não o que flui por ela. Quando o broker de inferência entrar, o valor passa de chave do provedor a token opaco do portal, e o perfil não muda — o nome continua sendo ditado pelo provedor, porque é o nome que o agente procura.

### D4 — Relocar a instalação do agente após instalar, em vez de depender de flag do instalador

O instalador do opencode é um script remoto cujas opções de destino não são contrato estável. A imagem instala como hoje e **move** o resultado para um caminho fora de `/root`, ajustando dono e o symlink.

*Por quê*: funciona independentemente do que o instalador aceite, e o resultado é verificável por teste de imagem (o binário existe, é executável pelo usuário do agente e não está sob `/root`).

### D5 — Modo de execução como coluna do sistema, imutável após a criação

`System` ganha um campo de modo de execução com dois valores — o antigo e o reduzido — com `server_default` do antigo na migração (para as linhas existentes) e default do reduzido no modelo (para linhas novas). O provisionamento lê o campo e só aplica usuário não-root e `cap_drop` no modo reduzido.

*Por quê*: é o que torna "só sistemas novos" implementável de verdade. Sem estado persistido, reconciliação e `refresh_connections` — que recriam o container — não teriam como distinguir um sistema antigo de um novo, e subiriam um container não-root sobre um workspace de dono root.

*Trade-off aceito*: a plataforma passa a conviver com dois modos por tempo indeterminado, e um sistema antigo só migra por ação explícita futura. A migração de sistemas antigos fica fora desta change, e o modo é consultável para que se saiba quem ainda está no antigo.

*Alternativa*: `chown` idempotente no provisionamento — foi descartada pelo usuário por tocar no dono dos arquivos de checkpoints git de sistemas em produção.

### D6 — Não renomear `/opencode-config`

O nome é específico de um agente, mas depois de D2 nenhum código o referencia como literal: o portal o monta a partir de `configs_dir` e o supervisor o descobre pelo perfil. Renomear seria churn sem mudança de comportamento, tocando todos os containers na recriação. O rename cabe na etapa em que o segundo perfil entra.

### D7 — `HOME` em diretório da imagem, não em tmpfs ou volume

Como o rootfs somente-leitura ficou para a etapa 2, o `HOME` do usuário do agente é um diretório da imagem com dono ajustado. O cache vive na camada de escrita do container.

*Por quê*: é o comportamento de hoje (com `HOME=/root` implícito) — o cache já se perde na recriação do container, então **não há regressão**. tmpfs e volume nomeado só passam a ser necessários quando o rootfs virar somente-leitura, e aí a decisão é informada pelo mapa de escrita medido na etapa 2.

## Risks / Trade-offs

- **O agente pode precisar escrever num caminho não previsto, e a falha aparece só em execução real** → mapear por execução `@llm_real` antes de fechar a etapa, e manter o `HOME` gravável (D7) para absorver cache inesperado. O risco é limitado: nesta change nada no filesystem é negado, só o dono muda.
- **O opencode pode querer escrever no cwd, que é o mount somente-leitura** → já é somente-leitura hoje e funciona; o teste de integração cobre subida do agente com o mount ro para detectar regressão.
- **Teto de processos mal calibrado derruba `uv`/`npm`, que abrem muitos processos** → calibrar com margem a partir de uma execução real de geração, e expor o teto como configuração junto dos outros limites, não como constante.
- **Dois modos de execução convivendo levam a bug só reproduzível no modo antigo** → o modo entra como parâmetro explícito nos testes de provisionamento, cobrindo os dois caminhos.
- **A extensibilidade do perfil é provada por um perfil de teste, não por um agente real** → risco assumido e nomeado: a prova real é a etapa 7. O teste evita o pior caso, que é descobrir na etapa 7 que o provisionamento tem o opencode embutido em algum lugar.

## Migration Plan

1. Migração Alembic encadeada ao head atual adiciona o modo de execução com `server_default` do modo antigo — toda linha existente fica explicitamente no modo antigo.
2. Build da nova imagem base. Sistemas existentes, ao serem recriados, sobem a imagem nova **no modo antigo** (usuário root explícito no `containers.run`), então a relocação do binário e o `HOME` novo não os afetam.
3. Sistemas criados a partir daí nascem no modo reduzido.
4. **Rollback**: reverter o código e a imagem. O campo de modo pode permanecer no banco sem efeito; nenhum dado de workspace é alterado em nenhuma direção, o que é a propriedade que torna esta etapa segura de reverter.

## Open Questions

- Qual o valor do teto de processos? Depende de medir uma geração real com `uv`; não muda specs, abordagem nem quebra de tarefas.
- O binário do agente fica em `/opt` ou num diretório do usuário do agente? Escolha de layout da imagem, resolvida na implementação.
