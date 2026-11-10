# Proposal

## Why

A plataforma hoje só executa o agente opencode. O roadmap de confinamento (docs/roadmap-confinamento-do-agente.md, etapa 7) chama isso de dívida arquitetural não testada: perfil de runtime, confinamento (Landlock/seccomp) e gate de destrutivas foram construídos para serem agnósticos de agente, mas nunca foram comprovados com um segundo agente real. A change `generalize-agent-runtime-plumbing` já removeu os literais hardcoded (imagem, mount path, protocolo de harness) do caminho de provisionamento e da fila de execução exatamente para habilitar este teste. Agora é a hora de registrar o agente Claude Code como segundo perfil e usar isso como critério negativo de prontidão: se adicionar este agente exigir tocar em qualquer código de segurança (proxy de gate, seccomp, Landlock), a abstração falhou.

## What Changes

- Registra o novo perfil `claude-code` em `agent_profiles.PROFILES`: imagem própria, comando/cwd apontando para um novo processo shim (ver Impact), `credential_env` literal `ANTHROPIC_API_KEY` (confirmado por spike real — mesmo header `x-api-key` que o broker já troca pro perfil opencode; ver design.md D3), `harness_protocol` novo (`claude-code-headless`), e `readable_paths`/`writable_paths` cobrindo `~/.claude`, `~/.claude.json` e `~/.config/anthropic` (achados por verificação real, mesmo método usado no perfil opencode — ver design.md).
- Introduz um processo shim HTTP, empacotado na nova imagem do agente, que o supervisor sobe como o `command` do perfil (processo de vida longa, como hoje é `opencode serve`) e que internamente invoca a CLI `claude` em modo headless (`--output-format stream-json`) por prompt, devolvendo os eventos via um endpoint HTTP/SSE equivalente ao do opencode.
- **Acesso ao banco do sistema** (achado durante a implementação, não previsto nesta seção originalmente): sem isto o claude-code não teria nenhum jeito de ler o banco — igual ao opencode, o acesso é só pelo MCP server `gated-mcp` já existente (`/opt/gated-mcp/mcp_server.py`, agnóstico de agente), carregado via `--mcp-config`/`--strict-mcp-config` (confirmado por spike real; ver design.md D6). A nova imagem copia `gated-mcp`; o writer de config do claude-code gera o `mcp-servers.json` com uma entrada por conexão do sistema, mesmo padrão de `write_opencode_config`.
- Introduz `ClaudeCodeHarness` (novo `HarnessPort` em `appaiforge/harness/`), registrado em `agent_queue.HARNESS_IMPLEMENTATIONS` sob `claude-code-headless`, falando com o shim do container do mesmo jeito que `OpencodeHarness` fala com `opencode serve` — sem alterar o dispatch já generalizado na change anterior.
- Decisão de escopo deliberada: `reply_gate`/`reply_question` do novo harness não têm equivalente nativo no v1 (a CLI headless do Claude Code não expõe um protocolo de permissão assíncrono como o `permission.asked` do opencode) — e isso é aceitável porque a spec `destructive-gate` já é agnóstica de protocolo de permissão do agente (a interceptação real de SQL destrutivo acontece no proxy de conexão ao banco, no data plane, "independente de como a SQL foi emitida e do protocolo de permissão do agente"). Nenhum código do gate, do proxy, do seccomp ou do Landlock é alterado por esta change.
- Generaliza o texto normativo de `agent-harness` que hoje nomeia "harness (opencode)" explicitamente na garantia de continuidade de contexto por sessão, para que a mesma garantia valha para qualquer harness registrado.
- Fora de escopo: seletor de perfil na UI de criação de sistema (`create_system` já aceita `agent_profile` desde a change anterior; a UI continua sem esse campo, igual a hoje) e suporte ao `question_asked`/pergunta nativa do opencode equivalente para Claude Code.

## Capabilities

### New Capabilities
(nenhuma — registrar um perfil novo e um harness novo é exatamente o que `agent-runtime` e `agent-harness` já prometem suportar sem mudança de spec; ver "Conjunto de perfis extensível" em agent-runtime)

### Modified Capabilities
- `agent-harness`: o requirement "Continuidade de contexto do agente dentro da sessão" nomeia "harness (opencode)" no texto normativo; passa a descrever a garantia de forma agnóstica de harness, já que agora há dois.

## Impact

- `portal/appaiforge/agent_profiles.py`: nova entrada em `PROFILES["claude-code"]`.
- `portal/appaiforge/harness/`: novo módulo `claude_code.py` com `ClaudeCodeHarness(HarnessPort)`.
- `portal/appaiforge/agent_queue.py`: nova entrada em `HARNESS_IMPLEMENTATIONS`.
- `base-image/`: novo componente shim (processo HTTP de vida longa que invoca `claude` headless por prompt) e uma nova imagem de container (Dockerfile próprio, menor superfície — só este agente instalado + `gated-mcp` copiado, igual à imagem opencode, pro acesso ao banco via MCP).
- `openspec/specs/agent-harness/spec.md`: requirement de continuidade de sessão generalizado.
- Nenhuma mudança em `afsupervisor` (o supervisor já só lê `command`/`cwd` do perfil, ADR 0003/0018), no proxy de gate de destrutivas, no seccomp ou no Landlock — esse é o próprio critério de sucesso da etapa 7.
