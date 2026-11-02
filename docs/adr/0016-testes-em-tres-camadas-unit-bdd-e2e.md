# 0016 — Testes em três camadas: unitários, BDD e E2E pelo browser

* Status: aceito
* Data: 2026-11-01
* Decidida em: change `appai-forge-mvp` (design D13, a pedido do usuário)

## Contexto

A plataforma combina IA, containers, proxy e UI — cada camada exige um tipo de confiança. E2E com LLM real é caro, lento e não determinístico. O usuário exigiu que todo o trabalho seja verificado com testes unitários, BDD e E2E pelo browser.

## Decisão

- **Unitários (pytest)**: lógica isolada — guardas RBAC, token HMAC, cifra, fila, adapter contra servidor falso, backoff do supervisor.
- **BDD (pytest-bdd)**: cada cenário WHEN/THEN das specs vira um cenário Gherkin em `tests/bdd/features/<capability>.feature`, tagado com a capability de origem; Postgres efêmero (testcontainers) e Docker real onde o cenário pede.
- **E2E (Playwright + pytest-playwright)**: jornadas completas no browser contra stack de teste dedicado, rodando por padrão com **harness fake** de `HarnessPort` (eventos reproduzidos sem LLM); um único cenário `@llm_real` manual valida o caminho real com GLM.

## Alternativas consideradas

- **behave** — descartado: runner separado do pytest.
- **Cypress/Selenium** — descartados: Cypress é ecossistema Node (segunda stack); Selenium é mais frágil e lento que Playwright.
- **E2E sempre com LLM real** — descartado: flakiness e custo por execução de CI.

## Consequências

Convenções: feature sem cenário de origem na spec é escopo indevido; unitários cobrem o interno, features o comportamento observável. Retries de E2E apenas em CI; trace viewer para diagnóstico.
