# Chave de LLM e broker de inferência

← [README](../README.md)

## Chave de LLM (para geração real)

O padrão do produto é GLM/Z.ai (ADR 0012). Obtenha uma chave e cadastre-a cifrada:

```bash
docker compose -f deploy/docker-compose.yml exec portal appaiforge set-provider-key --provider glm --key 'SUA_CHAVE_ZHIPUAI'
```

> Os comandos `docker compose -f deploy/...` funcionam de qualquer diretório; se preferir, `cd deploy` antes e use `docker compose exec portal ...` sem o `-f`.

Além do GLM, o admin pode cadastrar na UI provedores que falam o padrão OpenAI (o OpenRouter é um preset); os modelos são descobertos na própria rota do provedor, e cada sistema escolhe provedor e modelo. Chaves são globais por provedor, cifradas, e podem ser cadastradas, testadas e removidas pela UI de admin.

Sem chave, o portal opera em **modo fake** — todo o resto funciona. O compose sobe em `fake` por padrão; para usar o agente real defina `APPAIFORGE_HARNESS_MODE=opencode` (por exemplo em `deploy/.env`, que não vai para o git).

**Troubleshooting de provedor**: se uma execução falha com *"o provedor de LLM não retornou resposta (verifique chave, saldo e modelo configurados)"*, valide a chave diretamente — exemplo do erro `1113` (saldo insuficiente na Z.ai):

```bash
curl -s https://api.z.ai/api/coding/paas/v4/chat/completions \
  -H "Authorization: Bearer SUA_CHAVE" -H "Content-Type: application/json" \
  -d '{"model":"glm-4.6","messages":[{"role":"user","content":"ok"}]}'
```

## Broker de inferência (opcional — etapa 3 do confinamento)

Por padrão, a chave do provedor entra no container do sistema via env var. Com o **broker de inferência** ligado ([ADR 0020](adr/0020-broker-de-inferencia-com-litellm.md)), o container passa a carregar apenas um **token opaco** — o broker valida o token, resolve a execução ativa e injeta a credencial só no caminho de saída, com o [LiteLLM](https://docs.litellm.ai/) como backend de credencial e tradução de dialeto.

Para ligar, defina em `deploy/.env`:

```bash
APPAIFORGE_INFERENCE_BROKER_ENABLED=true
APPAIFORGE_LITELLM_API_KEY=sk-uma-chave-master-do-litellm
APPAIFORGE_INFERENCE_BROKER_SERVICE_TOKEN=um-token-entre-portal-e-broker
```

e suba o stack (`docker compose -f deploy/docker-compose.yml up -d --build`). Os serviços `litellm` e `broker` sobem na rede interna, sem porta publicada.

> **Banco do LiteLLM**: o serviço exige um database próprio (`litellm`) no Postgres — a migração Prisma cria as tabelas, mas não o database. O compose E2E cria no init do volume; no stack principal, crie uma vez (stack novo ou volume já existente):
>
> ```bash
> docker compose -f deploy/docker-compose.yml exec postgres \
>   psql -U appaiforge -c "CREATE DATABASE litellm;"
> ```
>
> Sem isso o `litellm` fica reiniciando até o banco existir; depois de criado, se recupera sozinho.

Como funciona:

- **Chaves**: o portal continua sendo a fonte única (cifradas no Postgres, ADR 0007). Ao cadastrar/remover uma chave na UI — e no boot do portal — os deployments são empurrados para a API administrativa do LiteLLM. Nada de chave de provedor em arquivo ou env do compose.
- **Containers**: com a flag ligada, sistemas novos (e existentes, recriados pela reconciliação) recebem o token opaco na env de credencial e o `opencode.json` aponta o provedor para o broker. `docker exec <sys> env` mostra só o token.
- **Revogação**: dono/admin pode revogar o acesso de um sistema (aba Configurações → "Revogar acesso de inferência": a versão do token sobe e o container é recriado) ou de uma sessão (botão na lista de sessões do chat — só aquela sessão é bloqueada).
- **Uso/custo**: o LiteLLM envia tokens e custo por execução para o portal (callback idempotente); a contagem caseira por provedor fica desligada.
- **Rollback**: desligar a flag e recriar os sistemas volta a injetar a chave do catálogo.

> A revogação por sistema e a rota do broker são **configuradas, não impostas** — fechar o perímetro de rede é a etapa 5 do [roadmap](roadmap-confinamento-do-agente.md).
