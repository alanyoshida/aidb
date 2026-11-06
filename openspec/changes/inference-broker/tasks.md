# Tasks

## 1. Spikes e bloqueios (fechar antes de codar o caminho crítico)

- [x] 1.1 Rodar o spike S7: confirmar que o opencode aceita um token opaco como valor da env de credencial (sem validação de formato) e que envia esse valor como `Authorization: Bearer`; registrar o resultado e o formato escolhido
- [x] 1.2 Rodar o spike S4: confirmar que o LiteLLM cobre GLM, OpenRouter e um provedor openai-compatible do catálogo, incluindo `/v1/messages`; registrar provedores que ficam de fora do rollout, se houver
- [x] 1.3 Rodar o spike S6: medir repasse de SSE (chunks incrementais, sem buffering) e cancelamento através de um proxy streaming; registrar o comportamento observado

## 2. Token opaco por sistema

- [x] 2.1 Adicionar migração Alembic com `systems.inference_token_version` (inteiro, default 0, backfill) encadeada ao head único; verificar `alembic heads` com um só head e upgrade/downgrade contra Postgres descartável
- [x] 2.2 Implementar a derivação `token = <system_id>.<HMAC(secret, "inference:"+system_id+":"+version)>` em um módulo do portal, com funções de emitir, validar e rotacionar; testar unitariamente token válido, adulterado e de versão antiga
- [x] 2.3 Implementar a revogação por sistema (incremento de `inference_token_version`) e expor a ação administrativa; testar que o token antigo deixa de validar e o novo continua válido

## 3. Broker de inferência

- [ ] 3.1 Criar o serviço do broker (entrypoint ASGI dedicado na imagem do portal) com healthcheck, configuração por env e roteamento `/v1/...` (OpenAI-compatible) e `/v1/messages` (Anthropic); testar que sobe e responde health
- [ ] 3.2 Implementar validação do token (assinatura + versão) e recusa sem token válido; testar requisição sem token, token adulterado e token revogado
- [ ] 3.3 Implementar a resolução de contexto com o portal (`system_id` → run/sessão ativos, provedor/modelo, revogação de sessão) com autenticação de serviço; testar sistema com execução ativa, sem execução ativa e com sessão revogada
- [ ] 3.4 Implementar injeção da credencial no caminho de saída e descarte do header de credencial do cliente; testar que o backend recebe apenas a credencial injetada
- [ ] 3.5 Implementar allowlist de destino de LLM e recusa de destino fora dela; testar destino permitido e destino recusado
- [ ] 3.6 Implementar proxy de streaming sem buffer e repasse na ordem; testar com upstream de chunks e assert de chegada incremental
- [ ] 3.7 Implementar cancelamento via chamada interna do portal (`/internal/cancel`) que encerra a conexão upstream; testar abort durante uma requisição em andamento
- [ ] 3.8 Implementar a superfície de revogação de sessão (portal marca, broker recusa) sem afetar outras sessões do mesmo sistema; testar revogação seletiva
- [ ] 3.9 Implementar o callback de uso do LiteLLM para o portal com `metadata` (`system_id`, `run_id`, `session_id`) e idempotência por evento; testar registro único e sem duplicar `TokenUsage`

## 4. Provisionamento e config do agente

- [ ] 4.1 Adicionar a flag `APPAIFORGE_INFERENCE_BROKER_ENABLED` (default false) em `config.py` e nos compose, mantendo o comportamento atual quando desligada
- [ ] 4.2 Com a flag ligada, `write_opencode_config()` passa a gravar `baseURL` do provedor apontando para o broker (por dialeto); testar que o `opencode.json` gerado contém o broker e não o provedor direto
- [ ] 4.3 Com a flag ligada, `provisioning` injeta o token opaco na env de credencial do perfil em vez da chave real, e não injeta a virtual key do LiteLLM; testar inspeção de env do container sem credencial utilizável
- [ ] 4.4 Garantir que a reconciliação reentrega o mesmo token (versionado) e que a recriação de um sistema existente aplica o novo caminho; testar em sistema `sandboxed`

## 5. LiteLLM e deploy

- [ ] 5.1 Adicionar o serviço `litellm` ao `deploy/docker-compose.yml` e ao `docker-compose.e2e.yml`, com config de provedores do catálogo e virtual key por sistema, sem porta publicada
- [ ] 5.2 Adicionar o serviço `broker` aos dois compose, na rede interna, com as envs de serviço (segredo HMAC compartilhado, master key do LiteLLM, URL do portal)
- [ ] 5.3 Configurar o callback de uso do LiteLLM apontando para o portal e validar a chamada fim a fim em ambiente local

## 6. Uso de tokens normalizado

- [ ] 6.1 Remover o `_token_count()` e a contagem por provedor do `harness/opencode.py`, mantendo o evento `usage` apenas quando ainda vier do harness; testar que o fluxo de chat não quebra
- [ ] 6.2 Persistir tokens e custo a partir do callback do LiteLLM em `TokenUsage` (ou campo derivado, conforme a decisão de schema), preservando a visibilidade por run/sessão; testar agregação após duas requisições

## 7. Testes de aceitação

- [ ] 7.1 Teste de integração: container de sistema não expõe chave utilizável em `docker exec <sys> env` (apenas o token) e o agente ainda completa uma execução
- [ ] 7.2 Teste de integração: revogar um sistema derruba só aquele sistema; revogar uma sessão derruba só aquela sessão
- [ ] 7.3 Teste de integração: streaming e cancelamento atravessam o broker sem buffering, com abort efetivo no upstream
- [ ] 7.4 Ajustar/estender os testes E2E do stack dedicado (8081) para o novo caminho com harness fake, sem apontar para o ambiente real

## 8. Documentação e decisão

- [ ] 8.1 Reconciliar a numeração de ADR (o ADR 0019 da etapa 2 não existe em `docs/adr/`) e registrar o ADR 0020 do broker/LiteLLM, documentando o híbrido e a virtual key no env como alternativa descartada
- [ ] 8.2 Atualizar a linha da etapa 3 no `docs/roadmap-confinamento-do-agente.md` com o status e os artefatos entregues
- [ ] 8.3 Documentar no `README.md`/guia operacional como configurar LiteLLM, o broker e o rollout por flag
