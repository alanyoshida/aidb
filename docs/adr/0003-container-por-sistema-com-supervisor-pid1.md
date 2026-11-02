# 0003 — Container por sistema com supervisor próprio como PID 1

* Status: aceito
* Data: 2026-11-01
* Decidida em: change `appai-forge-mvp` (design D3)

## Contexto

Cada sistema roda isolado em seu container e precisa, dentro dele, de dois processos geridos: o harness (`opencode serve`) e a app gerada — que deve ser (re)iniciada automaticamente quando o agente edita os arquivos, com sinal de saúde.

## Decisão

Imagem base `appaiforge/base:<ver>` (pinada na config do portal) com um supervisor Python próprio (~200 linhas, testável) como PID 1: sobe o `opencode serve` (porta interna 4096), vigia `/workspace/app` e reinicia a app gerada com backoff em caso de falha, e expõe `/healthz`.

## Alternativas consideradas

- **s6-overlay** — descartado: robustez e complexidade além do que o MVP precisa.
- **supervisord (pacote)** — descartado: configuração declarativa rígida, mais difícil de testar unitariamente a lógica de backoff/watchdog.

## Consequências

Código próprio a manter, compensado por testes unitários da lógica de backoff e comportamento previsível e instrumentável (task 4.2).
