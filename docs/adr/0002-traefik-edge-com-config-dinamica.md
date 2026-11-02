# 0002 — Traefik como edge proxy com config dinâmica

* Status: aceito
* Data: 2026-11-01
* Decidida em: change `appai-forge-mvp` (design D2)

## Contexto

As apps geradas (NiceGUI) precisam ser publicadas sob `/apps/{slug}` com WebSocket funcionando, e o conjunto de rotas muda a cada sistema criado ou arquivado. A plataforma deve permitir migrar para proxy por subdomínio no futuro sem refactor.

## Decisão

Traefik como único ponto de entrada (edge), com file provider: o portal escreve a configuração dinâmica de rotas em volume compartilhado ao provisionar/arquivar sistemas. O módulo "roteador de apps" do portal é o único dono dessas rotas — trocar path por subdomínio depois é mudar esse módulo. Apps NiceGUI honram `root_path=/apps/{slug}` (exigência das guidelines, injetada por env).

## Alternativas consideradas

- **Proxy in-process no FastAPI (ASGI)** — descartado: forwarding de WebSocket e strip de prefix ficam frágeis e manualmente mantidos.
- **Nginx com reload** — descartado: gerência de recarga e templates manuais onde o Traefik já entrega pronto.

## Consequências

Mais um container no stack. Quirks de path-prefix com NiceGUI/WebSocket são tratados no spike dedicado (task 6.1), com escape hatch para subdomínios já abstraído.
