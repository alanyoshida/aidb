# 0009 — Git por sistema com checkpoints por execução

* Status: aceito
* Data: 2026-11-01
* Decidida em: change `appai-forge-mvp` (design D9)

## Contexto

Código gerado por IA precisa de rollback confiável e de histórico/diff visível ao dono direto no portal.

## Decisão

`git init` no volume de workspace de cada sistema no provisionamento. Ao fim de cada execução bem-sucedida do agente, o portal commita (autor = editor que pediu) e registra em `checkpoints`. Rollback = `git reset --hard` para o sha + reinício da app pelo supervisor; diff e histórico aparecem na UI.

## Alternativas consideradas

- **Snapshots de volume** — descartados: pesados, sem diff legível.
- **Push automático para GitHub/GitLab** — descartado na v1: dependência externa e configuração por usuário; fica como opção futura.

## Consequências

Trabalho de run interrompida fica não-commitado no workspace (a run seguinte sobrescreve ou o dono commita manualmente). A persistência do volume é garantida pela reconciliação (ADR 0013).
