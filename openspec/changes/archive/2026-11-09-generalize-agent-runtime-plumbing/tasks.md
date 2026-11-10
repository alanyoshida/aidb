# Tasks

## 1. Schema de `System`

- [x] 1.1 Adicionar coluna de perfil de runtime do agente em `System` (nullable na migração) e verificar que a migração sobe limpa em um banco com sistemas existentes
- [x] 1.2 Backfill da coluna para `"opencode"` em todo `System` já existente e tornar a coluna `NOT NULL`; verificar que nenhuma linha fica com o valor nulo após a migração
- [x] 1.3 Preencher a coluna no fluxo de criação/provisionamento de sistema (perfil informado, ou perfil padrão da plataforma quando omitido) e verificar com um teste que um sistema novo nasce com o perfil correto persistido

## 2. Perfil declara imagem, mount path e protocolo de harness

- [x] 2.1 Adicionar `image`, `config_mount_path` e `harness_protocol` ao perfil `opencode` em `agent_profiles.py`, com os valores literais hoje hardcoded em outros lugares (`settings.base_image` atual, `/opencode-config`, `settings.opencode_port` atual), e verificar com teste unitário que `get_profile("opencode")` retorna os três campos
- [x] 2.2 Verificar que `get_profile()` sem argumento continua resolvendo o `DEFAULT_PROFILE` (comportamento inalterado para quem já depende disso), com teste existente passando sem mudança

## 3. `provisioning.py` consultando o perfil do sistema

- [x] 3.1 Trocar os call sites de `get_profile()` sem argumento por `get_profile(system.<campo-de-perfil>)` em `_broker_credential_env`, `write_agent_profile` e demais pontos identificados, e verificar com teste que o `env_name`/perfil usado reflete o perfil persistido do sistema, não sempre o default
- [x] 3.2 Usar `profile["image"]` no kwarg de imagem do container em `provision_system`, removendo o uso direto de `settings.base_image` nesse ponto, e verificar com teste de provisionamento que a imagem resolvida para um sistema no perfil `opencode` é idêntica à imagem que `settings.base_image` produzia antes da mudança
- [x] 3.3 Trocar o bind-mount literal `/opencode-config` e o `AIDB_AGENT_PROFILE` fixo por `profile["config_mount_path"]`, e verificar com teste que o container de um sistema no perfil `opencode` sobe com exatamente o mesmo mount e a mesma env var de antes
- [x] 3.4 Introduzir o registro `CONFIG_WRITERS` despachado por `profile["config_format"]`, com `write_opencode_config` registrada para `"opencode"`, fazendo `provision_system` chamar o registro em vez da função fixa; verificar com teste que um `config_format` desconhecido levanta erro explícito no provisionamento (fail loud, sem fallback silencioso)

## 4. `agent_queue.py` resolvendo harness por protocolo do perfil

- [x] 4.1 Introduzir o registro `HARNESS_IMPLEMENTATIONS` despachado por `profile["harness_protocol"]`, com `OpencodeHarness` registrada para `"opencode-http"`, construindo cada instância uma vez por protocolo (lazy, em cache); verificar com teste que a resolução por um protocolo diferente do padrão devolve a mesma instância em chamadas repetidas
- [x] 4.2 Fazer `AgentQueue.harness_for(system)` devolver `self.harness` (o harness injetado no construtor) quando o protocolo do sistema é igual ao do perfil padrão da plataforma, e só consultar `HARNESS_IMPLEMENTATIONS` para um protocolo diferente; trocar todo `self.harness.xxx(...)` por `self.harness_for(...).xxx(...)`; verificar com a suíte existente de `test_agent_queue_dispatch.py` (que injeta harness de teste direto no construtor, sem depender de `harness_mode`) que continua passando sem alteração
- [x] 4.3 Trocar `_harness_url(system)` para usar o `harness_port` do perfil do próprio sistema (via `get_profile`) em vez de `settings.opencode_port`, removendo a leitura direta desse setting; verificar com teste que a URL resolvida para um sistema no perfil `opencode` é idêntica à URL que `settings.opencode_port` produzia antes da mudança

## 5. Regressão de comportamento

- [x] 5.1 Rodar a suíte completa de testes de provisionamento e de fila de execução e verificar que passa sem alterar nenhuma asserção de comportamento (só remoção de referências diretas a `settings.base_image`/`settings.opencode_port` onde elas deixaram de existir)
- [x] 5.2 Escrever um teste de regressão dedicado que afirma, lado a lado, que os valores resolvidos do perfil `opencode` (`image`, `config_mount_path`, `harness_port`) são bit-a-bit iguais aos literais que eles substituíram, documentando a garantia de "zero mudança de comportamento para sistemas existentes" do design.md

## Workflow follow-up

- Arquivar esta change (`openspec archive generalize-agent-runtime-plumbing`) depois que a implementação e a suíte de testes passarem.
- Com esta change arquivada, retomar a etapa 7 do roadmap (registrar o perfil `claude-code` e o `ClaudeCodeHarness`) como uma change nova e isolada.
