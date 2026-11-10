# Proposal

## Why

A etapa 7 do roadmap de confinamento pede um segundo harness de agente (Claude Code CLI) como "teste da arquitetura": se adicioná-lo exigir tocar em código de segurança (proxy, seccomp, Landlock, gate), a abstração de perfil de runtime falhou. Explorando o código para preparar essa etapa, encontramos 5 pontos onde o provisionamento e a fila de execução já violam promessas que o próprio spec `agent-runtime` declara (perfil como fonte única consultada, perfil declara tudo que a plataforma precisa saber) — sem tocar em nenhuma camada de segurança:

1. `get_profile()` é chamado sem argumento em todo `provisioning.py`, sempre resolvendo o perfil padrão (`opencode`); `System` não tem onde registrar qual perfil usa.
2. `write_opencode_config()` é o único writer de configuração de agente, chamado incondicionalmente, sem despacho por `profile["config_format"]`.
3. A imagem do container é `settings.base_image`, um único valor global, não um campo do perfil — apesar do roadmap já prever "uma imagem por agente".
4. O bind-mount do diretório de configuração do agente no container usa o literal fixo `/opencode-config`, ignorando o `cwd`/caminho de config que o próprio perfil declara.
5. `agent_queue.get_queue()` instancia um único `HarnessPort` para todo o processo, escolhido só por um flag global `fake`/`real`; `_harness_url()` usa `settings.opencode_port`, um global separado que ignora o campo `profile["harness_port"]` já existente no perfil.

Fechar esses 5 pontos agora, sem ainda adicionar um segundo agente, deixa o registro de um perfil `claude-code` (o verdadeiro trabalho da etapa 7) como uma mudança pequena e isolada — essencialmente um novo registro em `agent_profiles.py` mais uma nova implementação de `HarnessPort` — ao invés de misturar esse trabalho com correções de plumbing que não são sobre o agente novo.

## What Changes

- `System` passa a ter um campo que registra qual perfil de runtime de agente usa, determinado no provisionamento (perfil padrão da plataforma quando nenhum é informado).
- Todo call site de `get_profile()` em `provisioning.py` passa a receber o perfil do `System`, nunca mais implicitamente o default.
- O perfil declara um campo de imagem de container; `provision_system` resolve a imagem do container do sistema a partir do perfil, não de `settings.base_image` (que passa a ser só o fallback do perfil padrão).
- O bind-mount do diretório de configuração do agente no container é derivado do caminho de configuração declarado no perfil, não do literal fixo `/opencode-config`.
- A escrita de configuração do agente passa a ser despachada por `profile["config_format"]`, com `write_opencode_config()` registrada como a implementação do formato `opencode` (sem introduzir, nesta change, um segundo formato real).
- `agent_queue.get_queue()` resolve o `HarnessPort` e a porta de conexão por sistema, a partir do perfil daquele sistema (`profile["harness_port"]`), em vez de uma única instância global de harness e de `settings.opencode_port`.
- Nenhuma mudança em `afsupervisor`, nos proxies de dados (SQL, HTTP), no classificador de gate, ou nas camadas de confinamento (seccomp/Landlock) — este é exatamente o código que a etapa 7 definiu como fora de escopo para o caso de teste do segundo agente.

## Capabilities

### New Capabilities

(nenhuma — esta change fecha lacunas de uma capability já existente, não introduz comportamento novo)

### Modified Capabilities

- `agent-runtime`: o perfil passa a declarar também a imagem de container do agente (requisito "Conteúdo declarativo do perfil"); nova exigência de que o componente do portal que dirige a execução do agente (hoje o `HarnessPort`) seja escolhido a partir do perfil do sistema, e não de uma instância única global.

## Impact

- `portal/appaiforge/models.py` (ou equivalente): novo campo em `System` para o perfil de runtime.
- `portal/appaiforge/agent_profiles.py`: perfis passam a declarar `image`; `get_profile()` continua igual na assinatura, mas passa a ser chamado com o perfil real do sistema em todos os call sites.
- `portal/appaiforge/provisioning.py`: `provision_system`, `write_opencode_config`, `write_agent_profile` e os helpers de env deixam de usar `get_profile()` sem argumento, `settings.base_image` fixo e o bind-mount literal `/opencode-config`.
- `portal/appaiforge/agent_queue.py`: `get_queue()`/`_harness_url()` passam a resolver harness e porta por sistema/perfil.
- Migração de banco para o novo campo de `System`.
- Testes de provisionamento e de fila de execução que hoje assumem o perfil `opencode` implícito.
