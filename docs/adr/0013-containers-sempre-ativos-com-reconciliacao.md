# 0013 — Containers sempre ativos, com reconciliação e limites padrão

* Status: aceito
* Data: 2026-11-01
* Decidida em: exploração `appai-forge-mvp` (design D12)

## Contexto

As apps geradas precisam estar no ar sem cold start; a plataforma roda em host único Docker conhecido (28 CPUs, 46 GB RAM) e deve sobreviver a reboots.

## Decisão

Containers de sistema sempre ativos com restart policy `unless-stopped`. Reconciliação no boot e periódica por labels (`appaiforge.system_id`, `appaiforge.version`): container ausente ou divergente é recriado com o mesmo workspace. Limites padrão por container (2 CPUs / 2 GB RAM / 10 GB disco) e teto de simultâneos (~10) configuráveis no portal.

## Alternativas consideradas

- **Auto-stop por inatividade** — adiado: cold start de segundos ao abrir a app; melhora RAM mas complica UX (fica no roadmap).
- **Liga/desliga manual** — descartado: sem garantia de disponibilidade.
- **Kubernetes** — descartado: complexidade prematura para host único.

## Consequências

Consumo constante de RAM proporcional aos sistemas ativos (limitado pelos tetos). Criação pode ser recusada ao atingir o teto (spec `container-lifecycle`).
