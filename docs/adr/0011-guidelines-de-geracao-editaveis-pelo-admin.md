# 0011 — Guidelines de geração centralizadas, editáveis pelo admin

* Status: aceito
* Data: 2026-11-01
* Decidida em: change `appai-forge-mvp` (design D10)

## Contexto

Gerações consistentes entre sistemas exigem que todo agente receba os mesmos padrões: layout de projeto, `root_path`, middleware de identidade, uso das envs de banco, idioma, estilo de CRUD/dashboards.

## Decisão

Documento de guidelines (PT-BR) versionado no portal, editável por administradores, materializado como `AGENTS.md` no workspace do sistema a cada atualização — lido pelo opencode em toda execução. Alterações valem a partir das execuções seguintes.

## Alternativas consideradas

- **Prompt mínimo por pedido** — descartado: cada sistema cresce orgânico e inconsistente.
- **Guidelines por sistema** — descartadas como padrão: matam a consistência global (notas por sistema podem ser adicionadas como extensão futura).

## Consequências

O admin é guardião do padrão de geração. Atualização não afeta runs em andamento — apenas as seguintes (spec `agent-harness`).
