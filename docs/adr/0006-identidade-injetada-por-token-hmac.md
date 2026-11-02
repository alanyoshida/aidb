# 0006 — Identidade do portal propagada às apps por token HMAC

* Status: aceito
* Data: 2026-11-01
* Decidida em: change `appai-forge-mvp` (design D6)

## Contexto

O usuário autentica no portal, não na app gerada; mas a app precisa saber quem está acessando (identificador e tipo) para funcionar como sessão própria, à prova de falsificação.

## Decisão

Token curto HMAC-SHA256 com segredo por sistema (injetado por env `APP_IDENTITY_SECRET`), TTL ~60s, payload `user_id`/tipo/exp. O portal emite o token no acesso a `/apps/{slug}`; a app troca por sessão própria via middleware padronizado nas guidelines. Token inválido/expirado → app recusa e o portal reautentica.

## Alternativas consideradas

- **JWT com assinatura assimétrica** — descartado: overkill para confiança single-portal (a app só precisa validar, nunca emitir).
- **Headers internos confiáveis do proxy** — descartado: forjáveis se alguém alcançar a rede interna.
- **Auth própria por app** — descartado: retrabalho em cada geração e UX de login duplicada.

## Consequências

O segredo de cada sistema precisa ser gerado no provisionamento e guardado. TTL curto tolera desvio de relógio moderado.
