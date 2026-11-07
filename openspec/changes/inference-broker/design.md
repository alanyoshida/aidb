# Design

## Context

Ver `proposal.md`. Estado atual relevante:

- `provisioning.write_opencode_config()` grava `baseURL` do provedor no `opencode.json`; `_provider_env()` injeta a chave real na env do container, com o nome vindo do `AgentProfile` (`FROM_PROVIDER` → `env_name` do catálogo).
- A fila garante **um run ativo por sistema** (`agent_queue`), e `AgentRun`/`ChatSession` já dão a atribuição que o broker precisa.
- O harness opencode conta tokens com `_token_count()` caseiro, por provedor; `TokenUsage` é persistido a partir do evento `usage`.
- Não há LiteLLM nem broker no stack; `deploy/docker-compose*.yml` ainda não têm os serviços.
- Etapas 1 e 2 concluídas: container não-root, perfil declarativo, seccomp/Landlock. O perímetro de rede (etapa 5) e o gate no data plane (etapa 4) não fazem parte desta change.

## Goals / Non-Goals

**Goals:**
- Nenhuma chave de provedor ou virtual key dentro do container do sistema; só token opaco.
- Broker compartilhado com validação de token, injeção da credencial, atribuição run/sessão, streaming/cancelamento e revogação.
- Uso de tokens/custo vindo do LiteLLM, sem contagem própria por provedor.
- Rollout sem quebrar sistemas existentes (recriação controlada).

**Non-Goals:**
- Tornar o broker **inescapável** (allowlist de rede/egress forçado) — etapa 5. Aqui ele é configurado, não imposto.
- Proxy de banco e gate no data plane — etapa 4.
- Telemetria OTel completa — etapa 6 (o broker apenas carrega `run_id` para correlação futura).
- Suporte a um segundo agente — etapa 7. O broker fica agnóstico de dialeto, mas o perfil novo não entra aqui.
- Failover/HA do broker em produção; alvo é o stack local.

## Decisions

### D1. Broker como serviço compartilhado, não sidecar
A identidade viaja no token, então o broker não depende da forma do perímetro (sidecar/netns no Docker vs iptables no k8s). Isso permite entregar a camada de troca já nesta etapa, sem esperar a etapa 5.

- **Alternativa descartada:** sidecar por container — duplicaria estado de token/revogação e amarraria o desenho ao perímetro Docker.

### D2. Token opaco derivado por sistema, com versão de revogação
Token = `<system_id>.<HMAC-SHA256(secret, "inference:" + system_id + ":" + version)>`, gerado no provisionamento e reentregue igual na reconciliação. Não exige armazenar plaintext; revogar um sistema = incrementar `inference_token_version` em `System` (migração nova) e recriar o container. O `system_id` visível no token é aceitável (não é segredo; a assinatura é).

- **Alternativa descartada:** token aleatório cifrado em tabela — mais simples de rotacionar, mas exige decifrar no provisionamento e guardar plaintext recuperável.
- **Por que não por run/sessão:** env de container é fixa na criação; token por run exigiria recriar o container a cada sessão (aviso "Contexto do agente reiniciado" indevido).

### D3. Broker resolve run/sessão no portal; LiteLLM é o backend
O broker valida o token (assinatura + versão), então consulta o portal por `system_id` para obter o run/sessão ativos, o provedor/modelo do sistema e se há revogação de sessão. A serialização "um run por sistema" dá a atribuição sem depender de header do agente (o opencode não manda `session_id` na chamada de LLM).

- **Alternativa descartada:** inferir sessão por conteúdo/headers do agente — frágil e específico do opencode.
- **LiteLLM** entra como backend de credencial e tradução de dialeto (OpenAI-compatible e Anthropic Messages), com virtual key por sistema. O broker escolhe a virtual key do sistema no caminho de saída.
- **Alternativa descartada:** broker falando direto com cada provedor — reimplementaria tradução de dialeto para multi-agente (etapa 7).
- **Alternativa descartada:** virtual key direto no env do container — granularidade por sessão impossível por env; é o motivo do híbrido.

### D4. Rotas do broker espelham o dialeto do agente
O broker expõe `/v1/...` (OpenAI-compatible) e `/v1/messages` (Anthropic). O `write_opencode_config()` grava `baseURL` apontando para o broker, por sistema; o broker encaminha ao caminho correspondente do LiteLLM. Como cada sistema tem um provedor, o dialeto vem do token, não do corpo.

- **Alternativa descartada:** broker com rota única `/v1` — quebraria o dialeto Anthropic usado na etapa 7.

### D5. Streaming sem buffer e cancelamento ativo
O broker usa proxy HTTP em streaming (httpx com `stream=True`), repassando chunks na ordem e sem acumular a resposta. Não reescreve o corpo. O cancelamento é explícito: o portal, ao interromper um run, chama o broker (`POST /internal/cancel` com `system_id`/`run_id`); o broker fecha a conexão upstream e propaga o abort. Se a conexão upstream cair, o broker encerra o stream sem inventar conteúdo.

- **Alternativa descartada:** bufferizar e reenviar — quebraria o requirement de streaming em tempo real e a interrupção.
- **Alternativa descartada:** inferir cancelamento pelo fechamento do cliente — não cobre o `/session/{id}/abort` do portal.

### D6. Uso/custo via callback do LiteLLM, com `metadata` injetado
O broker injeta `metadata: {system_id, run_id, session_id}` no corpo da requisição. Um callback do LiteLLM envia o uso normalizado (tokens, custo, modelo, virtual key) para um endpoint interno do portal, que persiste em `TokenUsage` de forma idempotente (`run_id` + id do evento LiteLLM). Para respostas não-streaming, o broker também pode registrar localmente como fallback; a fonte autoritativa é o LiteLLM.

- **Alternativa descartada:** o broker parsear `usage` do SSE — depende de o provedor devolver `usage` em stream; não é garantido (spike S6).
- **Alternativa descartada:** `_token_count()` caseiro — já é gambiarra por provedor e sai de cena.

### D7. Revogação com uma superfície efetiva
O broker é quem aceita ou recusa: valida assinatura/versão do token e consulta o estado de run/sessão no portal. Revogar o sistema = bump de versão (broker passa a recusar o token antigo). Revogar uma sessão = o portal marca a sessão e o broker recusa requisições atribuídas a ela. A virtual key no LiteLLM não é entregue a ninguém e só o broker a usa; revogá-la isoladamente não é o caminho de operação.

- **Alternativa descartada:** duas autoridades independentes (LiteLLM + broker) — obrigaria as duas a concordar e criaria bypass.
- **Alternativa descartada:** broker com cópia local do estado de sessão — divergência e janela de revogação.

### D8. Rollout por flag, recriação controlada
Enquanto `APPAIFORGE_INFERENCE_BROKER_ENABLED=false`, o comportamento atual (chave no env) é mantido. Ao ligar, o provisionamento grava token + `baseURL` do broker; sistemas existentes precisam ser recriados pela reconciliação (aviso "Contexto do agente reiniciado" previsto na spec `agent-harness`). A migração adiciona `inference_token_version` com default 0.

- **Alternativa descartada:** ligar direto sem flag — sem rollback rápido se o broker/LiteLLM falhar em algum provedor.

### D9. Deploy
Novos serviços no `docker-compose.yml` e no `docker-compose.e2e.yml`:
- `litellm`: imagem oficial, config com provedores do catálogo e virtual keys; sem porta publicada.
- `broker`: mesma imagem do portal, entrypoint dedicado (`uvicorn appaiforge.broker_app:app`), na rede interna; token de serviço para falar com o portal e master key do LiteLLM só no ambiente do broker.
No E2E o harness é `fake` e não chama LLM; os testes do broker usam um upstream LiteLLM/mock local determinístico.

## Risks / Trade-offs

- **S7 — opencode rejeita token opaco como credencial** → formato do token é um bearer comum; validar no spike antes de codar. Fallback: manter a env com formato aceito, sem valor utilizável.
- **S4 — LiteLLM não cobre GLM/OpenRouter/openai-compatible** → rodar o spike por provedor; se faltar, broker precisa de passthrough por provedor (aumenta escopo) ou o provedor fica de fora do rollout.
- **S6 — SSE atravessa o broker bufferizado** → teste com stream real e assert de chunks incrementais; `stream=True` + sem compressão no broker.
- **Cancelamento não chega** → endpoint interno `/internal/cancel` e timeout no upstream; teste de abort com app real.
- **Callback de uso duplicado/perdido** → chave de idempotência por evento; reconciliar contagem do LiteLLM com `TokenUsage`.
- **Broker é ponto único de falha** → healthcheck, restart policy e fail-closed com erro claro no chat; HA fica fora de escopo.
- **Segredo no broker** (master HMAC + master key do LiteLLM) → broker não compartilha ambiente com o container do agente; nunca loga header nem token.
- **Numeração de ADR** → o roadmap prevê ADR 0020 para esta etapa, mas o ADR 0019 (etapa 2) não existe em `docs/adr/`; reconciliar (criar 0019 retroativo ou renumerar) antes de gravar o 0020.

## Migration Plan

1. Migração Alembic: `systems.inference_token_version` (int, default 0, backfill) e, se necessário, índices para correlação de uso.
2. Subir `litellm` e `broker`; validar healthchecks e o callback de uso.
3. Rodar spikes S4/S6/S7 contra os provedores do catálogo.
4. Ligar `APPAIFORGE_INFERENCE_BROKER_ENABLED` e recriar um sistema de teste (modo sandboxed) verificando: `docker exec env` só tem token; app e harness funcionam; streaming e cancelamento funcionam.
5. Reconciliar os demais sistemas; rollback = desligar a flag e recriar (volta a injetar a chave do catálogo).

## Spike Results

### S7 — token opaco como credencial (fechado)

Verificado empiricamente com opencode 1.19.5 na imagem base (`appaiforge/base:0.1.0`), contra um mock OpenAI-compatible:

- O opencode aceita um valor arbitrário (token opaco) na env de credencial e **não valida o formato**.
- Ele repassa o valor como `Authorization: Bearer <token>` na chamada de saída.
- Achado de design: com o provider embutido `openai`, o opencode usa a **Responses API** (`/v1/responses`), não `/v1/chat/completions`. O broker precisa encaminhar também `/v1/responses` ao LiteLLM, além de `/v1/chat/completions` e `/v1/messages` — senão o caminho OpenAI-compatible quebra.
- Formato escolhido: token opaco comum (bearer), sem prefixo especial. O nome da env continua vindo do `AgentProfile`/catálogo (`FROM_PROVIDER`).

### S4 — cobertura do LiteLLM (fechado)

Verificado com a imagem oficial do LiteLLM (`ghcr.io/berriai/litellm:main-latest`) e config com os provedores do catálogo:

- **OpenRouter**: nativo (`openrouter/<modelo>`).
- **Anthropic**: nativo; a rota `/v1/messages` existe e encaminha (401 com chave dummy, como esperado).
- **OpenAI-compatible**: nativo; as rotas `/v1/chat/completions` e `/v1/responses` existem e encaminham.
- **GLM**: não há provider nativo `zhipuai/` nesta versão; carrega e roteia pela rota OpenAI-compatible com `api_base` do Z.ai/BigModel. Nenhum provedor do catálogo fica de fora — só o GLM exige o caminho OpenAI-compatible em vez de plugin nativo.
- Observação operacional: chamadas com falha de auth colocam o deployment em cooldown (429 "No deployments available") por alguns segundos; o broker deve tratar 429 do LiteLLM como erro de provedor, não como falha de token.

### S6 — SSE e cancelamento pelo proxy (fechado)

Medido com um proxy de streaming (leitura incremental do chunked do upstream, repasse imediato sem acumular):

- 8 chunks entregues com intervalos de 0,4s entre chegadas — entrega incremental, sem buffering.
- Ao fechar o cliente no meio do stream, a desconexão propagou ao upstream imediatamente (abort efetivo).
- Implicação para o broker: usar leitura em streaming e repassar chunk a chunk; ao cancelar, fechar a conexão upstream e não tentar ler o resto.

## Verificação real (etapa 3, 2026-11-07 — stack isolada 8081, OpenRouter/deepseek)

Geração real completa através de opencode → broker → LiteLLM → OpenRouter, com app gerada e executada. Achados que a implementação exigiu corrigir no caminho:

1. **LiteLLM exige banco próprio para a API administrativa** (`/model/new` sem DB falha) e `STORE_MODEL_IN_DB=True`: adicionado `DATABASE_URL` (database `litellm` no mesmo Postgres) e a env aos compose.
2. **O broker precisa do mesmo `SECRET_KEY` do portal** — é a chave mestra do HMAC do token. Sem compartilhar, todo token dá 401 (compose corrigido nos dois stacks).
3. **O agente envia só o modelID** (`deepseek/deepseek-chat`); o nome registrado no LiteLLM é `<provider_id>/<model>`. O broker passou a **reescrever o `model`** para o nome canônico vindo do contexto do portal (`apply_context`) — de quebra, impede que o agente peça modelo fora do catálogo.
4. **O logger HTTP genérico do LiteLLM é Enterprise** (e o nome correto seria `generic_api`): substituído por um **callback customizado em Python** montado no container (`deploy/litellm/custom_callbacks.py` via `custom_callback_path`), que posta o `standard_logging_object` para o portal. O metadata da requisição chega em `metadata.requester_metadata` (não em `spend_logs_metadata`).
5. **Tokens de serviço precisam viver em `deploy/.env`**: a interpolação do compose não enxerga overrides de serviço, e o token na URL do callback/interpolação voltava ao fallback (causa silenciosa de 401).
6. Observação operacional: revogação disparada de um processo transitório (CLI) perde o reprovision assíncrono — o thread daemon morre com o processo. Pela UI (processo do portal) funciona; reconciliação cobre o resto.

Resultados: `docker exec <sys> env` só com token opaco (zero `sk-or-`); execução real concluída; revogação por sistema (token antigo 401, novo 409 sem run, container recriado com o token da nova versão); revogação de sessão (403 com a run ativa, demais sessões do mesmo sistema intactas); interrupção propagada ao broker (`/internal/cancel` 200, run interrompida); reprovision reentrega o token idêntico; uso/custo registrado fim a fim (8.620 in / 491 out, US$ 0,0032, id idempotente); suíte E2E (8081) com flag ligada: 19/23 verdes, 2 falhas de contenção do suite (passam isolados) e 1 falha pré-existente do diálogo BigQuery (bisect prova que já falhava em `47af312`, fora do escopo).

## Open Questions

- Definir a retenção/limpeza do mapeamento de sessão revogada (sem impacto nas specs) — pode ficar para a implementação.
- Definir se o custo será gravado em `TokenUsage` (campo novo) ou derivado — decisão de schema durante a implementação, sem alterar o comportamento observável.
