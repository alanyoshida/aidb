# Design

## Context

Ver `proposal.md` — Why. Estado atual que molda a solução:

- `harness/opencode.py:PROVIDER_MAP` traduz o id do portal para o providerID do catálogo (models.dev) e o nome da env de chave; provedores fora do mapa caem num fallback `{PROVIDER.upper()}_API_KEY`.
- `provisioning.write_opencode_config` monta `opencode.json` com `model: "<providerID>/<model>"` e só injeta `baseURL` no caso `zhipuai` (GLM).
- `provisioning._provider_env` lê a chave de `ProviderKey` (global por provedor) e injeta a env.
- `config.py` tem `PROVIDERS`/`KNOWN_MODELS` fixos; `system_create` e o editar-provedor usam isso.
- `llm-provider-keys` (recém-sincronizada) já cobre cadastro/troca/remoção/teste de chave global por provedor, na UI de admin.

## Goals / Non-Goals

**Goals:**
- Permitir cadastrar qualquer provedor que fale o padrão OpenAI, mais o OpenRouter, sem alterar código.
- Modelos obtidos do próprio provedor (rota de modelos), não digitados.
- Sistema escolhe provedor/modelo do catálogo; o agente recebe a configuração correta no `opencode.json` + a env da chave.

**Non-Goals:**
- Não substitui o gate de SQL, a auditoria de gestão nem o RBAC.
- Não implementa faturamento/cota por provedor nem múltiplas chaves por provedor.
- Não muda o comportamento dos provedores nativos já existentes (GLM/Anthropic/OpenAI) além de passarem a vir do catálogo.

## Decisions

### 1. Catálogo em tabela própria `llm_provider`

```
llm_provider
  id           str (pk)         -- id do portal (ex.: "glm", "openrouter", "minha-ia")
  label        str              -- rótulo exibido
  kind         str              -- "native" | "openai-compatible"
  provider_id  str              -- providerID do opencode (native) ou o próprio id (compatible)
  base_url     str | null       -- exigido para "openai-compatible"; p/ native pode ser nulo
  env_name     str              -- nome da env da chave no container (ex.: OPENROUTER_API_KEY)
  models       JSON             -- lista de modelos descoberta/seedada
  is_preset    bool             -- presets não podem ser removidos, só editados
  created_at   datetime
```

Um seed na migration cria os presets: `glm` (native `zhipuai`, base_url do GLM), `anthropic` (native), `openai` (native), `openrouter` (native `openrouter`). O `ProviderKey` continua sendo a chave, agora referenciando `llm_provider.id`.

*Alternativa considerada:* estender `ProviderKey` com `base_url`/`models` — recusada: mistura credencial com definição de provedor e não suporta nativos sem chave própria.

### 2. Modelos descobertos na rota do provedor

Ação "Buscar/Atualizar modelos" chama `GET {base_url}/models` (adicionando `/v1` quando a base não o tiver) com a chave como Bearer; para o OpenRouter, `GET https://openrouter.ai/api/v1/models`. A lista resultante (`data[].id`) é gravada em `llm_provider.models` e usada no select do sistema. Presets nativos podem ter a lista seedada (ex.: GLM) e permitir atualização.

*Alternativa considerada:* o admin digitar a lista — recusada pelo usuário; bate na rota.

*Risco de formato:* endpoints de `/models` variam; a descoberta é best-effort e não bloqueia o cadastro (a lista pode ser editada depois).

### 3. Provisão ao agente por tipo de provedor

Em `write_opencode_config`, além do `model: "<provider_id>/<model>"`:

- **openai-compatible** → declara
  `provider.<id> = { "npm": "@ai-sdk/openai-compatible", "name": <label>, "options": {"baseURL": <base_url>}, "models": { <m>: {} ... } }`.
- **native** → mantém o providerID do catálogo; GLM segue com `baseURL` (o mesmo comportamento de hoje).

A env da chave (`_provider_env`) passa a usar `llm_provider.env_name`.

*Risco:* o opencode precisa resolver o pacote `@ai-sdk/openai-compatible` no container (instalação em runtime via rede). Mitigação: documentar a dependência de rede e prever `npm` na imagem base se necessário; validar com um provedor real no `@llm_real`.

### 4. Catálogo é a fonte das opções de provedor/modelo do sistema

`config.PROVIDERS`/`KNOWN_MODELS` deixam de ser a lista canônica: `system_create` e o editar-provedor leem o catálogo (`llm_provider`). O modelo é escolhido entre `llm_provider.models`. O padrão continua GLM.

### 5. Permissões e auditoria

Catálogo é admin-only (UI + serviço). Toda escrita do catálogo (cadastro/edição/remoção/descoberta de modelos) registra na trilha de auditoria de gestão (recurso `provider`), sem segredos. Chaves continuam pela gestão existente (`provider_key.*`).

## Risks / Trade-offs

- **[Risco]** `@ai-sdk/openai-compatible` precisa ser resolvido no container do sistema (rede). → **Mitigação**: validar o caminho real no `@llm_real`; se falhar, prever o pacote na imagem base.
- **[Risco]** Rota `/models` heterogênea entre provedores. → **Mitigação**: descoberta best-effort, com edição manual da lista como escape.
- **[Risco]** Sistemas existentes apontando para `glm/anthropic/openai` precisam continuar funcionando. → **Mitigação**: presets seedados com os mesmos ids (`glm`,`anthropic`,`openai`), mantendo `PROVIDER_MAP` como compatibilidade.
- **[Risco]** `base_url` pode conter credencial embutida (token na URL). → **Mitigação**: guardar a chave só em `ProviderKey` (cifrada) e não aceitar credencial na `base_url`; registrar a base_url na auditoria é permitido.

## Migration Plan

- Uma migration cria `llm_provider` e faz o seed dos presets (glm/anthropic/openai/openrouter). Nenhuma coluna existente é alterada; `ProviderKey` permanece.
- Deploy é rebuild normal do `portal`; sem backfill de dados de domínio.
- Rollback: reverter o commit e a migration (drop da tabela). Sistemas existentes voltam à lista fixa.

## Open Questions

- Precisamos de chave para provedores nativos "sem chave" (ex.: um OpenAI-compatible local sem auth)? Assumimos chave obrigatória por ora; decidível depois sem mudar specs.
- Deixar o admin editar manualmente a lista de modelos, ou apenas via descoberta? Assumimos permitir edição como escape.