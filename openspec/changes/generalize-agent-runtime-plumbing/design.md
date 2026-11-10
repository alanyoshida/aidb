# Design

## Context

Ver proposal.md - Why para os 5 pontos encontrados. Resumo do estado atual relevante para o desenho:

- `agent_profiles.PROFILES` hoje tem uma única entrada (`"opencode"`), com campos `command`, `cwd`, `config_path`, `config_format`, `credential_env`, `harness_port`, `readable_paths`, `writable_paths`, `connect_tcp_ports`. Não existe campo de imagem de container nem de protocolo de harness.
- `provisioning.provision_system` chama `get_profile()` sem argumento (3x), usa `settings.base_image` como imagem de todo container, e monta o diretório de config do agente sempre em `/opencode-config` (bind read-only), com `AIDB_AGENT_PROFILE` fixado em `/opencode-config/agent-profile.json`.
- `write_opencode_config()` é chamada incondicionalmente - não há despacho por formato.
- `agent_queue.get_queue()` guarda uma única instância de `HarnessPort` por processo (`OpencodeHarness` ou `FakeHarness`, só por `settings.harness_mode`); `_harness_url(system)` usa `settings.opencode_port`, ignorando `profile["harness_port"]`.
- `System` não tem coluna para registrar qual perfil usa.

## Goals / Non-Goals

**Goals:**
- Fazer o `System` registrar seu perfil de runtime no provisionamento (spec `agent-runtime` - "Perfil de runtime por sistema").
- Tornar imagem de container, caminho de montagem da config e protocolo de harness campos do perfil, consultados por sistema - não globais.
- Preservar bit-a-bit o comportamento atual dos sistemas existentes, todos no perfil `opencode`: mesma imagem, mesmo mount path, mesma porta, mesmo harness.

**Non-Goals:**
- Não registra o perfil `claude-code` nem implementa um `ClaudeCodeHarness` nesta change - fica para a etapa 7 propriamente, depois desta.
- Não altera `afsupervisor`, sandbox (seccomp/Landlock), os proxies de dados (SQL/HTTP) nem o classificador do gate - nenhum desses pontos é tocado, por design.
- Não resolve a menção textual a "(opencode)" dentro do requisito "Continuidade de contexto do agente dentro da sessão" do spec `agent-harness` - é uma inconsistência textual pré-existente, sem efeito de comportamento, fora do escopo desta change.
- Não muda o protocolo de wire do opencode nem o formato do `opencode.json` em si.

## Decisions

**1. Novo campo em `System` para o nome do perfil.** Resolvido uma vez em `provision_system`, no momento do provisionamento (perfil informado ou perfil padrão da plataforma), e persistido - nunca re-resolvido dinamicamente depois. Isso é literal ao requisito "determinado no provisionamento" do spec. Alternativa considerada: resolver o perfil a cada operação a partir de alguma config solta - rejeitada porque o spec já exige "exatamente um perfil... determinado no provisionamento", e resolver dinamicamente abriria a porta para o perfil de um sistema mudar sem reprovisionamento.

**2. Perfil ganha `image` e `config_mount_path`.** `image`: referência de imagem de container (hoje, para o perfil `opencode`, igual ao valor atual de `settings.base_image` - zero mudança de comportamento). `config_mount_path`: caminho absoluto dentro do container onde o diretório de config é montado read-only (hoje, para `opencode`, o literal atual `/opencode-config`). `provision_system` usa `profile["image"]` no kwarg de imagem do container e `profile["config_mount_path"]` como alvo do bind-mount; `AIDB_AGENT_PROFILE` passa a ser `f"{profile['config_mount_path']}/agent-profile.json"`. Alternativa considerada: derivar o mount path de `profile["cwd"]` - rejeitada porque `cwd` é o workspace do agente (onde ele trabalha), e o diretório de config é deliberadamente um mount separado, fora do workspace (ver spec `agent-runtime` - "Perfil entregue ao container sem segredo": "montado... fora do workspace").

**3. Despacho do writer de config por `profile["config_format"]`.** Um registro simples (`CONFIG_WRITERS = {"opencode": write_opencode_config}`) em `provisioning.py`; `provision_system` chama `CONFIG_WRITERS[profile["config_format"]](...)`. Um formato desconhecido levanta erro explícito no provisionamento, seguindo o mesmo princípio de "falha explícita, nunca fallback silencioso" que o supervisor já aplica a perfil ausente. Esta change não adiciona um segundo formato real - só o ponto de extensão.

**4. Perfil ganha `harness_protocol`; despacho de `HarnessPort` por esse campo, não por sistema.** Achado ao ler `harness/opencode.py`: `OpencodeHarness` já recebe `system` como parâmetro em cada chamada (`create_session`, `run`, `reply_gate`...) e resolve a URL base por chamada via `resolve_base_url(system)`; seu estado interno (`_aborting`, `_message_roles`, `_pending_prompt`) é indexado por `session_id`, nunca por sistema. Uma única instância já atende qualquer número de sistemas concorrentes com segurança, desde que todos falem o mesmo protocolo - não há necessidade de uma instância (nem de um cache) por sistema. O que falta é só despachar por **protocolo**, não por sistema: um registro pequeno (`HARNESS_IMPLEMENTATIONS = {"opencode-http": lambda: OpencodeHarness(_harness_url)}`) em `agent_queue.py`, com uma instância construída uma vez por protocolo (lazy, na primeira vez que esse protocolo é usado).

`AgentQueue.harness_for(system)` resolve o protocolo do perfil daquele sistema; quando é igual ao protocolo do perfil padrão da plataforma, devolve direto `self.harness` (o harness injetado no construtor) - só um protocolo DIFERENTE do padrão passa pelo registro/cache. Achado ao implementar: isto substitui o que seria um caso especial para `settings.harness_mode == "fake"` - `AgentQueue(harness)` já é como os testes unitários de `agent_queue.py` injetam um `HarnessPort` de teste diretamente (ex.: `ScriptedHarness`), sem nenhuma relação com `harness_mode`; tratar "fake" como caso especial teria ignorado esse harness injetado sempre que `harness_mode` não fosse literalmente `"fake"` no ambiente de teste, quebrando toda aquela suíte. "Mesmo protocolo do perfil padrão → usa o harness do construtor" cobre os dois casos (fake e teste unitário) sem precisar conhecer nenhum dos dois. Alternativa considerada (cache de instância por sistema, com invalidação no reprovisionamento) - descartada: seria estado extra para gerenciar (e invalidar) sem necessidade, já que nenhuma instância de harness guarda estado por sistema hoje.

**5. `_harness_url(system)` usa o perfil do próprio sistema.** Resolve `harness_port` do perfil persistido em `system` (via `get_profile(system.agent_profile)`), nunca `settings.opencode_port`. O setting é removido do código (deixa de ser lido); o valor que ele tinha hoje passa a viver como o `harness_port` do perfil `opencode` em `agent_profiles.py`. Como a resolução já acontece por chamada (`resolve_base_url(system)`), isto não exige nenhuma instância nova nem cache - é uma mudança local dentro da própria função.

## Risks / Trade-offs

- [Migração de schema pode divergir do comportamento atual para sistemas já existentes] → migração faz backfill explícito de todo `System` existente para o perfil `opencode` (o único que existia antes desta change); nenhum sistema fica sem perfil.
- [Novos campos (`image`, `config_mount_path`, `harness_protocol`) no perfil `opencode` podem divergir dos literais hardcoded atuais e quebrar silenciosamente os sistemas em produção] → teste de regressão novo que afirma que os valores resolvidos do perfil `opencode` são bit-a-bit iguais aos literais que ele substitui (`settings.base_image` atual, `/opencode-config`, `settings.opencode_port` atual), além dos testes de provisionamento já existentes.

## Migration Plan

1. Migração de banco: nova coluna em `System` (nullable na migração, backfill para `"opencode"` em todas as linhas existentes, depois `NOT NULL`).
2. `agent_profiles.py`: adicionar `image`, `config_mount_path`, `harness_protocol` ao perfil `opencode`, com os valores literais atuais.
3. `provisioning.py`: trocar os 3 call sites de `get_profile()` sem argumento por `get_profile(system.agent_profile_name)`; introduzir `CONFIG_WRITERS`; trocar `settings.base_image` e o literal `/opencode-config` pelos campos do perfil.
4. `agent_queue.py`: cache de harness por sistema; `_harness_url` lendo o perfil do sistema.
5. Rodar a suíte de provisionamento e de fila de execução; nenhum teste deve precisar mudar sua asserção de comportamento (só, no máximo, deixar de referenciar `settings.base_image`/`settings.opencode_port` diretamente).
6. Rollback: revert padrão da migração (coluna é aditiva, sem dependentes ainda) - não há segundo perfil em produção que dependa dela.
