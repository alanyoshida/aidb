# 0012 — LLM via API externa; provedor por sistema (default GLM); custo só com visibilidade

* Status: aceito
* Data: 2026-11-01
* Decidida em: exploração `appai-forge-mvp` (design D11)

## Contexto

Rodar pesos de modelo dentro de cada container inviabiliza N sistemas (GPU/RAM); o host tem GPU de 8 GB, insuficiente para servir vários modelos. Provedores externos têm custo e desempenho distintos por caso de uso.

## Decisão

O harness de cada sistema chama **API externa** de LLM. Chaves por provedor (GLM/Z.ai padrão, Anthropic, OpenAI) são cifradas na configuração do portal e injetadas apenas como env no container. Cada sistema escolhe provedor+modelo no cadastro (default GLM). Consumo de tokens é registrado por execução e exibido em dashboards por sistema/usuário — **sem bloqueio** na v1.

## Alternativas consideradas

- **Modelo local compartilhado (Ollama no host)** — descartado como padrão: limita a modelos 7–8B e a um sistema por vez na GPU; permanece opção futura para dados sensíveis.
- **Pesos dentro de cada container** — descartado: inviável em escala.
- **Bloqueio de custo por teto** — adiado: é política de produto para change futura; dashboards dão a visibilidade mínima agora.

## Consequências

Fatura pode crescer sem freio automático — mitigada por visibilidade. Dados do banco consultados pelo agente fluem ao provedor externo (aceito para o contexto interno).
