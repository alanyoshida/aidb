# Proposal

## Why

Hoje a chave real do provedor de LLM entra no container de cada sistema como variável de ambiente, legível por todo o processo — inclusive o bash do agente e a app gerada — e é global por provedor, sem atribuição de consumo por execução. A etapa 3 do roadmap fecha essa exposição: o container passa a carregar apenas um token opaco e um broker compartilhado troca esse token pela credencial no caminho de saída, com atribuição por sessão e revogação central. É o primeiro marco demonstrável do roadmap (container sem chave de LLM dentro).

## What Changes

- Novo serviço compartilhado **broker de inferência** que valida o token opaco do container, resolve run/sessão ativos do sistema, injeta a credencial no header e encaminha ao LiteLLM.
- Repasse de streaming (SSE) sem buffering, com backpressure/timeout, e cancelamento propagado ao provedor.
- Credencial vinda do cliente é descartada; o broker não repassa a credencial que o agente porventura envie.
- Allowlist de destino no broker, recusando requisição sem token válido — o broker não pode virar relay aberto na rede interna.
- **LiteLLM** entra no stack como backend de credencial e tradução de dialeto (OpenAI-compatible e Anthropic Messages), com virtual key por sistema.
- Provisionamento passa a escrever `baseURL` → broker no config do agente e a injetar um **token opaco** (não a chave real) na env de credencial cujo nome vem do `AgentProfile`.
- Atribuição de sessão: o broker pergunta ao portal qual run/sessão estão ativos naquele sistema, aproveitando a serialização já existente de um run por sistema — sem depender de header do agente.
- Revogação centralizada no broker (token do container + mapeamento de sessão), para não existirem duas superfícies de revogação que precisem concordar.
- Uso de tokens/custo passa a vir do LiteLLM (normalizado), substituindo o `_token_count()` caseiro do harness opencode.
- **BREAKING** (interno): a env de credencial do container deixa de conter a chave real; qualquer verificação que espere a chave no ambiente passará a ver o token opaco.

## Capabilities

### New Capabilities

- `inference-broker`: broker compartilhado de inferência — identidade por token opaco, injeção de credencial no caminho de saída, streaming/cancelamento, atribuição de run/sessão, revogação e allowlist de destino.

### Modified Capabilities

- `llm-provider-keys`: a chave cadastrada passa a ser consumida pelo broker; o container de sistema deixa de receber a chave e a revogação efetiva passa a ser a do broker.

## Impact

- `portal/appaiforge/provisioning.py` — config do agente (`baseURL` do broker) e env do container (token opaco em vez da chave).
- Novo serviço do broker e `portal/appaiforge/harness/opencode.py` — uso de tokens normalizado, sem contagem própria.
- `deploy/docker-compose.yml` e `deploy/docker-compose.e2e.yml` — serviços LiteLLM e broker, além das configurações de chave virtual.
- Modelo/migração Alembic para token opaco por sistema e correlação de uso por run/sessão.
- Specs: nova `inference-broker` e delta em `llm-provider-keys`.
- ADR 0020 (roadmap): registra o híbrido com LiteLLM e por que a virtual key direto no env foi descartada. Observação: o ADR 0019 previsto para a etapa 2 não existe em `docs/adr/` — a numeração precisa ser reconciliada antes de gravar o 0020.
- Testes: unitários e de integração, incluindo SSE sem buffering, cancelamento e revogação seletiva por sistema/sessão. Spikes S4, S6 e S7 do roadmap precisam ser fechados antes/durante a implementação.
