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

## Nota de implementação (change `portal-reconcile-loop`, 2026-11-21)

Até esta change a reconciliação existia (`provisioning.reconcile()`) mas o portal em execução nunca a chamava. Agora ela roda numa thread de fundo iniciada na subida do portal: uma passada logo ao subir, sem atrasar o `/api/health`, e depois uma a cada `APPAIFORGE_RECONCILE_INTERVAL` segundos (padrão 300; `0` mantém só a passada da subida). A mesma passada vale para os dois drivers (container Docker ou Pod Kubernetes). Ela pula o sistema que o portal está criando, recriando ou removendo naquele momento (trava por sistema, num processo do portal só), relê o estado antes de agir e isola falhas por sistema; um sistema recriado com sucesso volta a ativo.
