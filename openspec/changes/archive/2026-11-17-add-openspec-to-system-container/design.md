# Design

## Context

- A imagem base (`base-image/Dockerfile`) já tem Node 22 (usado pelos MCP servers via npx) e o opencode pinado. Não tem o CLI do OpenSpec.
- O portal materializa `AGENTS.md` e `portal_templates/` no workspace a cada execução (`guidelines.materialize`), com caminho próprio para o driver Kubernetes (escrita via exec no Pod).
- O supervisor (`afsupervisor/supervisor.py`) é o PID 1 do container e inicia o harness (`start_harness`) dentro do próprio container, nos dois drivers.
- A saída HTTPS dos sistemas passa pelo proxy obrigatório com allowlist (ADR 0024); o registry npm não está liberado.
- Testado localmente com OpenSpec 1.15.0: `openspec init --tools opencode` cria `openspec/config.yaml`, `openspec/specs/`, `openspec/changes/archive/`, `.opencode/commands/opsx-*.md` e `.opencode/skills/openspec-*/SKILL.md`. Não toca em `AGENTS.md`. No opencode os comandos se chamam `/opsx-propose` (hífen), não `/opsx:propose`.

## Goals / Non-Goals

**Goals:**
- Mesmo comportamento nos drivers Docker e Kubernetes, sem código novo no portal para escrever arquivos do OpenSpec.
- Nenhuma dependência de rede no runtime.

**Non-Goals:**
- Perfil `claude-code` (imagem própria, sem Node para isso hoje) — change futura.
- Visualizar changes/specs do sistema numa tela do portal.
- Atualizar automaticamente a versão do OpenSpec sem rebuild da imagem.

## Decisions

### D1. CLI instalado na imagem base, versão pinada

`npm install -g @fission-ai/openspec@1.15.0` no `Dockerfile` (ARG `OPENSPEC_VERSION`), seguindo o padrão de pinagem da imagem. Telemetria do CLI desligada por ENV (`OPENSPEC_TELEMETRY=0`), já que a saída é bloqueada pelo proxy e não deve gerar tentativas.

*Alternativa*: liberar o registry npm na allowlist e usar `npx` — rejeitada: dependência de rede e versão não determinística em runtime.

### D2. Bootstrap no supervisor, antes do harness

Novo passo `ensure_openspec(workspace)` chamado pelo supervisor antes de `start_harness`:

```
workspace sem openspec/      -> openspec init --tools opencode --language pt-BR <workspace>
workspace com openspec/      -> openspec update <workspace>   (só comandos/skills; preserva changes/specs)
erro ou timeout (30s)        -> loga e segue (não bloqueia agente nem app)
```

Roda como o mesmo usuário do harness (identidade reduzida, ADR 0018), para os arquivos ficarem com o dono certo. Como roda dentro do container, vale igual para Docker e Kubernetes sem tocar no `materialize` do portal.

**Achado na validação real (task 5.2):** o `opencode serve` do sistema roda com
`cwd=/opencode-config` (perfil `opencode`), fora do workspace — de propósito, para o agente não
alterar a própria config. Por isso ele **não** carrega `/workspace/.opencode/` e listava só os
comandos embutidos. Subir o agente em `/workspace` ou mandar `directory=/workspace` na API faria o
opencode também carregar config de projeto gravável pelo agente (`/workspace/.opencode/opencode.json`),
um furo de confinamento. Solução: o bootstrap liga `~/.config/opencode/commands` (diretório global
de comandos do opencode, na camada gravável do container) a `/workspace/.opencode/commands` — só os
comandos (prompts) ficam visíveis, nunca config. Verificado contra o opencode 1.19.5: os `opsx-*`
aparecem em `GET /command` com `source: command` e o endpoint de comando expande o template. Como o
agente não roda dentro do workspace, as guidelines dizem para rodar o CLI `openspec` a partir de
`/workspace`. As skills `openspec-*` não ficam visíveis ao agente; os comandos `opsx-*` trazem as
instruções completas e não dependem delas.

Mais dois achados da mesma validação real, no modo `sandboxed`:
- O CLI do OpenSpec (Node) aborta com erro de config do OpenSSL porque o Landlock bloqueava
  `/etc/ssl/openssl.cnf`; o perfil `opencode` passa a liberar a leitura desse arquivo.
- Como o agente inicia em `/opencode-config`, o CLI não achava a raiz e o agente perguntava se
  devia inicializar um projeto novo. Guidelines não bastam: o opencode do sistema não carrega o
  `AGENTS.md` do workspace (a config não tem `instructions` apontando para ele — achado anterior a
  esta change, registrado à parte), e guidelines editadas pelo admin não recebem a seção nova. O
  adapter acrescenta aos argumentos de todo `/comando` uma linha dizendo que o projeto é
  `/workspace`; o template do comando a inclui em `$ARGUMENTS`.

*Alternativa*: o portal escrever os arquivos no `materialize` — rejeitada: exigiria o CLI no portal (ou copiar arquivos gerados de uma versão), duplicaria o caminho Docker/Kubernetes e sairia de sincronia com a versão do CLI da imagem.

### D3. Guidelines

Nova seção nas guidelines padrão (`_DEFAULT` em `guidelines.py`) explicando os comandos `/opsx-propose`, `/opsx-explore`, `/opsx-apply`, `/opsx-archive`, quando usá-los e que os artefatos ficam em `openspec/`. Guidelines já editadas pelo admin no banco não são alteradas — o admin incorpora a seção se quiser.

### D4. Checkpoints

Nada muda: `openspec/` e `.opencode/` são arquivos comuns do workspace e entram no checkpoint git como os demais. Confirmar que nenhum `.gitignore` do workspace os exclui.

### D5. Autocomplete de comandos no chat

- **Fonte**: nova operação `list_commands(system) -> list[{name, description}]` no `HarnessPort`. No opencode, consulta a API do `opencode serve` que lista os comandos do workspace (endpoint a confirmar na versão pinada 1.19.5 — task 5.1; a lista inclui os `.opencode/commands/*.md` com o `description` do frontmatter). No `FakeHarness`, devolve os comandos lidos de `.opencode/commands/` do workspace (determinístico para o E2E). No `claude-code`, lista vazia (fora do escopo).
- **Cache**: por sistema, ~60 s em memória no portal, invalidado quando o container é recriado ou ao fim de uma execução (o agente pode ter criado comandos). Falha ou timeout curto (2 s) → lista vazia, sem erro visível.
- **UI**: no `ui.input` do chat (`data-testid=chat-input`), um menu de sugestões ancorado ao campo aparece quando o texto começa com `/` e ainda não tem espaço; filtra por prefixo; setas/Enter/Tab escolhem e completam `"/<nome> "` sem enviar; Esc fecha. Enter com o menu fechado mantém o comportamento atual de envio. Itens com `data-testid=chat-command:<nome>`.
- **Envio**: o texto vai ao harness como hoje; o opencode reconhece `/<comando> args` e executa o comando. Se o adapter atual enviar prompts por um endpoint que não interpreta comandos, usar o endpoint de comando do opencode quando a mensagem começar com `/<comando conhecido>` (confirmar na task 5.1).

*Alternativa*: lista fixa de comandos no portal — rejeitada: sai de sincronia com a versão do CLI e não mostra comandos próprios do workspace.

**Confirmado no opencode 1.19.5 (task 4.1, contra `opencode serve` real na imagem base):**
- `GET /command` devolve a lista `[{name, description, source, template, ...}]`. `source` é
  `command` (arquivos `.opencode/commands/*.md`, ex.: `opsx-propose`) ou `skill` (as skills
  `openspec-*` aparecem como comandos também). O autocomplete usa só `source == "command"`, para
  não duplicar cada fluxo (comando + skill de mesmo propósito).
- `POST /session/{id}/prompt_async` **não** interpreta comandos: o texto `/opsx-explore x` chega
  cru ao modelo. Por isso a task 4.3 se aplica.
- `POST /session/{id}/command` com `{"command": "<nome sem barra>", "arguments": "<resto>",
  "model": "<provider>/<model>"}` expande o template do comando (a mensagem de usuário gravada é o
  texto do `opsx-explore.md` com os argumentos). A chamada é síncrona (só responde ao fim da
  execução), então o adapter a dispara em segundo plano e acompanha o mesmo stream `/event`.
  Comando inexistente responde erro (500 na 1.19.5) na hora.

## Risks / Trade-offs

- [O `openspec update` muda arquivos de comando a cada reinício quando a versão da imagem muda] → efeito desejado; aparece no próximo checkpoint como diff de `.opencode/`.
- [Landlock/sandbox (ADR 0019) pode impedir o bootstrap de escrever no workspace se rodar antes do sandbox estar configurado com o usuário certo] → executar com a mesma identidade e confinamento do harness; teste de integração cobre.
- [Imagem um pouco maior] → um pacote npm; aceitável.
- [API de listagem de comandos do opencode muda entre versões] → isolada no adapter `opencode.py`; teste de contrato contra a versão pinada.
- [Agente usa o fluxo errado (`/opsx:propose` com dois-pontos)] → guidelines usam o nome do opencode.

## Migration Plan

Rebuild da imagem base e recriação dos containers (reconciliação). Sistemas existentes ganham OpenSpec no próximo start, sem perder dados. Rollback: imagem anterior; os arquivos `openspec/` e `.opencode/` deixados no workspace são inertes sem o CLI.
