# 0020 — Broker de inferência: token opaco no container, LiteLLM como backend

* Status: aceito
* Data: 2026-11-06
* Decidida em: change `inference-broker` (design D1–D9; capability `inference-broker`, etapa 3 do roadmap)
* Relacionada: [0007](0007-metadados-em-postgres-e-credenciais-cifradas.md), [0012](0012-llm-via-api-externa-provedor-por-sistema.md), [0018](0018-perfil-de-runtime-do-agente-e-identidade-reduzida.md), [0019](0019-sandbox-seccomp-landlock-no-supervisor.md)

## Contexto

A chave real do provedor de LLM entra no container de cada sistema como variável de ambiente ([ADR 0012](0012-llm-via-api-externa-provedor-por-sistema.md)), legível por todo o processo — inclusive o bash do agente e a app gerada — via `/proc/self/environ`. É uma chave global por provedor, sem atribuição de consumo por execução, e exfiltração é um `curl`. O sandbox ([ADR 0019](0019-sandbox-seccomp-landlock-no-supervisor.md)) confina o filesystem, mas não o que já está no ambiente.

Esta é a etapa 3 de [`docs/roadmap-confinamento-do-agente.md`](../roadmap-confinamento-do-agente.md) e o primeiro marco demonstrável do roadmap: container sem root, confinado e **sem chave de LLM dentro**, sem tocar no gate de SQL.

## Decisão

**Híbrido: token opaco no container + broker compartilhado + LiteLLM como backend de credencial.**

**Token opaco derivado por sistema, com versão de revogação.** `token = <system_id>.<HMAC-SHA256(secret, "inference:" + system_id + ":" + version)>`. Gerado no provisionamento e reentregue igual pela reconciliação — nada de plaintext armazenado. Revogar um sistema = incrementar `systems.inference_token_version` e recriar o container; o token antigo deixa de validar. O `system_id` visível no token é aceitável: a assinatura é o segredo.

**Broker compartilhado, não sidecar.** Serviço na rede interna que valida o token, consulta o portal pelo contexto ativo (run/sessão, provedor/modelo, sessão revogada — a serialização "um run por sistema" do [ADR 0004](0004-opencode-serve-atras-de-adapter-com-fila-no-portal.md) dá a atribuição sem depender de header do agente) e encaminha ao LiteLLM **com a credencial injetada só no caminho de saída**, descartando qualquer credencial enviada pelo cliente. Expõe as rotas por dialeto (`/v1/...` para OpenAI-compatible — incluindo `/v1/responses`, descoberto em spike — e `/v1/messages` para Anthropic). Como a identidade viaja no token, o broker não depende da forma do perímetro (sidecar no Docker vs `iptables` no k8s) — a etapa 5 apenas torna o caminho inescapável.

**LiteLLM como backend de credencial e tradução de dialeto.** Multi-agente é multi-dialeto (OpenAI-compatible hoje, Anthropic Messages na etapa 7); o LiteLLM expõe e traduz ambos. O portal é a **fonte única das chaves** (cifradas no Postgres, [ADR 0007](0007-metadados-em-postgres-e-credenciais-cifradas.md)): ao cadastrar/remover uma chave — e no boot — o portal empurra os deployments para a API administrativa do LiteLLM. O container do sistema não recebe a chave do provedor nem virtual key nenhuma.

**Streaming e cancelamento sem buffer.** O broker repassa os chunks na ordem, sem acumular, e o portal cancela a requisição upstream via `POST /internal/cancel` na interrupção da execução.

**Uso e custo via callback do LiteLLM.** O broker injeta `metadata` (`system_id`, `run_id`, `chat_session_id`) no corpo; o callback do LiteLLM envia o uso normalizado para um endpoint interno do portal, que grava `TokenUsage` de forma idempotente por id de evento. A contagem caseira por provedor (`_token_count()`) sai de cena.

**Rollout por flag.** `APPAIFORGE_INFERENCE_BROKER_ENABLED=false` mantém o comportamento atual (chave no env); ao ligar, o provisionamento grava token + `baseURL` do broker e os sistemas existentes são recriados pela reconciliação, com o aviso "Contexto do agente reiniciado" previsto na spec `agent-harness`.

## Alternativas consideradas

- **Virtual key do LiteLLM direto no env do container** — descartada: env de container é fixa na criação, então trocar a key por sessão exigiria recriar o container a cada sessão (aviso indevido de "Contexto do agente reiniciado"). É o motivo do híbrido: a camada de troca (broker) entre o token fixo e a credencial por requisição.
- **Sidecar por container** — duplicaria estado de token/revogação e amarraria o desenho ao perímetro Docker.
- **Broker falando direto com cada provedor** — reimplementaria a tradução de dialeto que a etapa 7 (multi-agente) exige; o LiteLLM expõe `/v1/chat/completions`, `/v1/responses` e `/v1/messages` nativamente.
- **Token aleatório cifrado em tabela** — mais simples de rotacionar, mas exige guardar plaintext recuperável e decifrar no provisionamento.

## Consequências

- Nenhuma credencial de LLM dentro do container do sistema; `docker exec <sys> env` mostra só o token opaco, inútil fora do broker.
- Revogação com uma superfície efetiva: versão do token (sistema inteiro) e marcação de sessão (`chat_sessions.inference_revoked`), ambas recusadas pelo broker sem afetar os demais.
- O broker é ponto único de falha: healthcheck, restart policy e falha clara no chat; HA fora de escopo do stack local.
- O caminho do broker é **configurado, não imposto** — um agente que descobrir o endereço do provedor ainda pode chamá-lo direto. Impor o perímetro é a etapa 5; exfiltração pelo prompt (endpoint de LLM legítimo) permanece irredutível.
- GLM não tem provider nativo no LiteLLM: roteia via OpenAI-compatible com `api_base` do Z.ai — nenhum provedor do catálogo fica de fora.
- Falhas de auth a jusante colocam o deployment do LiteLLM em cooldown (429 transitório); o broker trata como erro de provedor, não de token.
