# 0004 — Harness opencode serve atrás de adapter; fila no portal

* Status: aceito
* Data: 2026-11-01
* Decidida em: change `appai-forge-mvp` (design D4)

## Contexto

O portal precisa dirigir um agente de código dentro de cada container (sessões, mensagens, stream de eventos, interrupção). A API HTTP do `opencode serve` é experimental e pode mudar. Dois editores não podem executar o agente do mesmo sistema simultaneamente.

## Decisão

Interface interna `HarnessPort` (criar/listar sessões, enviar mensagem, stream de eventos, interromper, uso de tokens) com implementação `OpencodeHarness` que fala HTTP com o `opencode serve` do container. Eventos normalizados (`run_started`, `file_edited`, `command_run`, `tool_output`, `usage`, `run_finished`); versão do opencode pinada na imagem. A fila "um agente por sistema por vez" é do portal (tabela `agent_runs`, ordem de chegada), não do harness.

## Alternativas consideradas

- **Mini-harness próprio** — descartado para a v1: peça inteira a construir e manter; opencode já entrega o loop de agente.
- **Acoplamento direto ao opencode** — descartado: mudança de API quebraria o portal inteiro.
- **Fila no harness** — descartada: o opencode não a oferece; e a fila é política de produto (visível aos editores), não do harness.

## Consequências

Trocar o harness ou absorver mudança de API fica localizado no adapter. O mapeamento exato de eventos é validado no spike (task 5.1) antes de congelar o adapter.
