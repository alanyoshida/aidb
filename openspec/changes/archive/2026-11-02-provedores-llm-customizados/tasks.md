# Tasks

## 1. Catálogo de provedores (dados + serviço)

- [x] 1.1 Criar o modelo `LlmProvider` (id, label, kind, provider_id, base_url, env_name, models, is_preset) e a migration Alembic que cria a tabela e faz o **seed dos presets** (glm, anthropic, openai, openrouter); verificar com `alembic upgrade head --sql` e conferir os presets na tabela após aplicar.
- [x] 1.2 Implementar o serviço `services/catalog.py` (listar, criar, editar, remover — presets não removíveis —, admin-only) com auditoria de gestão (recurso `provider`, sem segredos); verificar com `tests/unit/test_llm_catalog.py` (CRUD, preset protegido, permissão, auditoria).

## 2. Descoberta de modelos na rota do provedor

- [x] 2.1 Implementar `catalog.discover_models(provider)` batendo em `GET {base_url}/models` (com `/v1` quando ausente) usando a chave cadastrada, com tratamento especial para o OpenRouter, e guardando o resultado em `llm_provider.models`; verificar com unit test que simula a resposta HTTP (lista `data[].id`) e um caso de falha.

## 3. Provisão do provedor ao agente

- [x] 3.1 Ajustar `provisioning.write_opencode_config` e `_provider_env` para gerar, por tipo: `openai-compatible` → `provider.<id>` com `npm:"@ai-sdk/openai-compatible"`, `options.baseURL` e `models`; nativo → providerID do catálogo (GLM mantém `baseURL`); e injetar a env por `llm_provider.env_name`. Verificar com unit test que lê o `opencode.json` gerado nos dois casos.
- [x] 3.2 Garantir compatibilidade dos presets existentes: sistemas com `glm`/`anthropic`/`openai` continuam gerando o mesmo `opencode.json`/env de hoje; verificar com unit test comparando a saída para o GLM.

## 4. UI do catálogo (admin)

- [x] 4.1 Na área "Provedores de LLM" do `/admin`, listar os provedores do catálogo com ações: cadastrar (id/rótulo/base_url/tipo), editar, remover (presets sem remover) e **Buscar modelos**; verificar por E2E em `tests/e2e/test_llm_keys.py` (cadastrar provedor custom, buscar modelos, remover).

## 5. Escolha de provedor/modelo pelo catálogo

- [x] 5.1 Trocar a lista fixa por leitura do catálogo em `system_create.py` (select de provedor) e no editar provedor de `system_detail.py`, com o select de modelo vindo de `llm_provider.models`; verificar por E2E (provedor do catálogo aparece na criação; trocar para um provedor custom reflete no cabeçalho).

## 6. Chave e teste por provedor do catálogo

- [x] 6.1 Fazer `provider_keys` operar sobre os provedores do catálogo (listar inclui custom/OpenRouter) e `test_stored_key` usar a `base_url` do provedor; verificar com unit tests (incluindo teste com a chamada simulada de um provedor custom).

## 7. Verificação de integração

- [x] 7.1 Rodar `cd portal && uv run pytest tests/unit tests/bdd` — verdes.
- [x] 7.2 Subir o stack E2E dedicado e rodar `uv run pytest tests/e2e` — verdes.

## Workflow follow-up

- Validar manualmente o caminho real com um provedor OpenAI-compatible (`@llm_real`): criar o sistema, conversar e confirmar que o opencode resolve `@ai-sdk/openai-compatible` no container.
- Arquivar a change depois de concluída e revisada.