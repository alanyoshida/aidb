# 0014 — RBAC com tipos globais de usuário; só editor cria sistemas

* Status: aceito
* Data: 2026-11-01
* Decidida em: exploração `appai-forge-mvp` (decisões interativas, com correção do usuário)

## Contexto

O portal serve dois públicos: quem constrói sistemas (editores) e quem apenas usa as apps geradas. O usuário definiu que **somente editores criam sistemas** e que grupos concedem acesso a N sistemas.

## Decisão

Tipo global único por usuário: `admin` (tudo: usuários, grupos, chaves, todos os sistemas), `editor` (cria sistemas e torna-se dono; cadastra conexões; conversa com o agente) e `app_user` (só usa apps de sistemas acessíveis). Grupos N:M com sistemas; usuário pertence a N grupos; acesso direto adicional pelo vínculo de dono ou admin. Autenticação local e-mail/senha.

## Alternativas consideradas

- **Papel por sistema (usuário↔sistema)** — descartado para a v1: mais flexível, mas mais UI e validação; "somente editores criam" viraria permissão extra.
- **Global + downgrade por sistema** — descartado: meio-termo com complexidade dos dois mundos.

## Consequências

Reclassificar um usuário muda sua capacidade no portal inteiro. Necessidades por-sistema (ex.: consultor read-only num sistema) ficam para change futura — o modelo não as impede.
