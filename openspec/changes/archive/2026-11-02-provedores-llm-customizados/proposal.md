# Proposal

## Why

Hoje os provedores de LLM são um conjunto fixo embutido no código (`glm`, `anthropic`, `openai`): `PROVIDER_MAP` no harness, `KNOWN_MODELS` no config e um `opencode.json` que só trata o GLM com `baseURL`. Usar qualquer outro provedor que fale o **padrão OpenAI**, ou o **OpenRouter**, exige alterar o código do portal. Isso trava a operação em três provedores e impede credenciais/endpoints próprios.

## What Changes

- **Catálogo global de provedores de LLM** gerenciado pelo admin: id, rótulo, `base_url` e tipo (`openai-compatible` para provedores que falam o padrão OpenAI; `native` para os já previstos pelo catálogo do opencode). O **OpenRouter** entra como preset pré-carregado (e GLM/Anthropic/OpenAI seguem como presets).
- **Descoberta de modelos** batendo na rota do provedor (`GET {base_url}/models`, com a chave), guardando a lista no provedor — o select de modelo do sistema usa essa lista, sem digitação manual.
- **Chave por provedor do catálogo**: reusa a gestão de chaves existente; a chave passa a valer para qualquer provedor do catálogo (incluindo custom e OpenRouter) e o teste usa a `base_url` do provedor.
- **Criar/editar sistema** escolhe provedor e modelo a partir do catálogo (dinâmico), no lugar da lista fixa.
- **Provisionamento**: o `opencode.json` do sistema passa a declarar o provedor do catálogo — para `openai-compatible`, `provider.<id>` com `npm:"@ai-sdk/openai-compatible"`, `options.baseURL` e a lista de modelos; para nativo (OpenRouter/GLM/…), o providerID do catálogo — e a env da chave é injetada no container.

## Capabilities

### New Capabilities

- `llm-provider-catalog`: catálogo de provedores de LLM OpenAI-compatible (com OpenRouter como preset), gerenciado pelo admin — cadastro/edição/remoção, descoberta de modelos na rota do provedor e provisão do provedor ao agente do sistema.

### Modified Capabilities

- `llm-provider-keys`: a chave passa a ser por provedor do catálogo (qualquer um, inclusive custom e OpenRouter) e o teste de chave usa a `base_url` cadastrada do provedor.
- `system-management`: o provedor e o modelo oferecidos no cadastro/edição do sistema passam a vir do catálogo de provedores, e não de uma lista fixa.

## Impact

- **Código**: `portal/appaiforge/models.py` (tabela do catálogo) + migration; `portal/appaiforge/services/` (novo serviço de catálogo; ajuste em `provider_keys` e `systems`); `portal/appaiforge/config.py` (substitui `PROVIDERS`/`KNOWN_MODELS` fixos); `portal/appaiforge/provisioning.py` e `portal/appaiforge/harness/opencode.py` (gerar provedor no `opencode.json`); `portal/appaiforge/ui/{admin,system_create,system_detail}.py`; `portal/appaiforge/cli.py`.
- **Dados**: nova tabela de catálogo + seed dos presets (migration Alembic).
- **Infra**: `base-image` já traz opencode 1.19.5; o provedor OpenAI-compatible depende do opencode resolver `@ai-sdk/openai-compatible` no container (risco de rede — ver design).
- **Testes**: unit (catálogo, descoberta de modelos, geração do `opencode.json`, chave/teste por provedor), BDD e E2E (`system_create`/editar provedor listando o catálogo; admin gerenciando provedor).