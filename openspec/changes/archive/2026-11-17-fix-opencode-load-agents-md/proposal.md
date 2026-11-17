## Why

O agente opencode dos sistemas não recebe as guidelines da plataforma. O portal grava o `AGENTS.md` no workspace antes de cada execução, mas o `opencode serve` roda com `cwd=/opencode-config` — fora do workspace, de propósito, para não carregar config de projeto que o agente pode editar — e a config gerada não tem `instructions` apontando para o arquivo. Confirmado no opencode 1.19.5 pinado: com a config atual o conteúdo do `AGENTS.md` não chega ao modelo; com `"instructions": ["/workspace/AGENTS.md"]` chega. O requisito "Guidelines editáveis pelo admin" (agent-harness) não é cumprido hoje para o perfil `opencode`, que é o padrão.

## What Changes

- `write_opencode_config` passa a gravar `"instructions": ["/workspace/AGENTS.md"]` no `opencode.json` do sistema.
- Teste de contrato com o opencode pinado prova que o conteúdo do `AGENTS.md` entra no prompt enviado ao provedor e que uma alteração no arquivo vale para a mensagem seguinte.
- Sistemas existentes passam a carregar as guidelines quando o container for recriado (a config é fixada na criação).

## Capabilities

### New Capabilities

_(nenhuma)_

### Modified Capabilities

- `agent-harness`: o requisito "Guidelines editáveis pelo admin" ganha cenário explícito de que as guidelines chegam ao agente no perfil `opencode`.

## Impact

- `portal/appaiforge/provisioning.py` (`write_opencode_config`).
- Testes: `portal/tests/unit/test_llm_provisioning.py`, `portal/tests/integration/test_openspec_system.py` (ou arquivo de contrato próprio).
- Sem mudança na imagem base, no supervisor nem no confinamento: o caminho é absoluto e já legível pelo agente.
