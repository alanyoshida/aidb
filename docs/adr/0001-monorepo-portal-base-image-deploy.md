# 0001 — Monorepo com três entregáveis

* Status: aceito
* Data: 2026-11-01
* Decidida em: change `appai-forge-mvp` (design D1)

## Contexto

A plataforma tem três entregáveis que evoluem juntos: o portal (FastAPI + NiceGUI), a imagem base dos containers de sistema e o deploy (compose do stack). O projeto está em fase de descoberta, com mudanças cross-cortes frequentes.

## Decisão

Monorepo único com `portal/`, `base-image/` e `deploy/`, versionados juntos.

## Alternativas consideradas

- **Repositórios separados** — descartados: overhead de sincronizar versões entre três repos na fase inicial, sem equipe para justificar.
- **Um só diretório sem separação** — descartada: imagem base e deploy têm ciclos e consumidores distintos do código do portal.

## Consequências

Mudanças que atravessam os três entregáveis são atômicas (um commit). CI deve detectar qual diretório mudou para não rebuildar tudo.
