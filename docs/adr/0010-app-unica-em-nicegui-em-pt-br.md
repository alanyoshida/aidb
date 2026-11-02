# 0010 — App única em NiceGUI por sistema, interface em PT-BR

* Status: aceito
* Data: 2026-11-01
* Decidida em: exploração `appai-forge-mvp` (decisão interativa; refletida no design D10 e specs)

## Contexto

As apps geradas são painéis administrativos, dashboards e relatórios sobre bancos de dados, escritas por agentes. Consistência entre sistemas e previsibilidade da geração importam mais que liberdade de stack. O usuário pediu "backend e frontend em Python".

## Decisão

Uma única app **NiceGUI** por sistema: CRUD, dashboards e relatórios são rotas/páginas dentro da mesma aplicação, 100% Python, com WebSocket embutido. Interface em português do Brasil por padrão (configurável por sistema no futuro).

## Alternativas consideradas

- **Reflex** — descartado: apps mais ricas visualmente, mas build pesado no container e mais espaço para o agente errar.
- **FastAPI + React** — descartado: frontend sai do Python e a geração fica menos determinística.
- **Streamlit** — descartado como padrão: bom para relatórios, limitado para CRUD administrativo.
- **Agente escolhe a stack por sistema** — descartado: sistemas inconsistentes entre si.

## Consequências

WebSocket é requisito do proxy (ADR 0002). O padrão NiceGUI fica cristalizado nas guidelines (ADR 0011); apps extraordinárias podem reabrir a decisão com novo ADR.
