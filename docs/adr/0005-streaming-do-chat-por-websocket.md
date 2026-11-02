# 0005 — Streaming do chat por WebSocket

* Status: aceito
* Data: 2026-11-01
* Decidida em: change `appai-forge-mvp` (design D5)

## Contexto

O chat do portal mostra o trabalho do agente em tempo real (arquivos, comandos) e permite interromper no meio da execução — exige canal de eventos de saída e comando de controle de entrada.

## Decisão

WebSocket entre o browser e o portal: eventos normalizados do adapter fluem para o chat; interrupção é cancelamento da run propagado ao harness pelo mesmo canal de controle.

## Alternativas consideradas

- **SSE** — descartado: unidirecional; a interrupção precisaria de um segundo canal HTTP e a fila/estado ficariam espalhados.
- **Polling** — descartado: latência e experiência ruins para streaming de eventos.

## Consequências

Precisa tratar reconexão e multrasessão de WebSocket (que o NiceGUI já usa — mesma infraestrutura). Testes E2E com Playwright cobrem o streaming de ponta a ponta.
