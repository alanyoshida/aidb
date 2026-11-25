# Design

## Context

Ver proposal.md (Why). No driver Docker, `reconcile_one` busca o container do sistema pelo nome:
ausente vira `ComputeUnitNotFound` (o orquestrador recria tudo), de outro dono vira
`ComputeUnitOwnedElsewhere`; presente, ele só confere se os sidecars existem e recria os ausentes.
O estado do container (`running`, `exited`...) nunca é olhado.

Os sidecars (`-dbgate`, `-httpsproxy`) sobem com `network_mode: container:<id do sistema>`.
Verificado no Docker local:

- com o container do sistema parado, um sidecar que continua rodando fica num namespace de rede
  órfão; depois de um `start` no container do sistema, o sidecar segue na rede antiga (quebrado);
- `start` num sidecar enquanto o container do sistema está parado falha;
- `start` no container do sistema e depois no sidecar deixa os dois na mesma rede.

O portal nunca para container de sistema de propósito (arquivar e excluir removem), e a
reconciliação já pula sistemas arquivados e em provisionamento. Container parado de sistema
reconciliável é sempre divergência.

## Goals / Non-Goals

**Goals:**
- Container de sistema parado volta a rodar na próxima passada, com os sidecars na rede dele.

**Non-Goals:**
- Atualizar imagem de container antigo (parado ou rodando) — tema separado.
- Driver Kubernetes.
- Mudar o estado do sistema na reconciliação ao religar.

## Decisions

**D1 — Religar, não recriar.** Container presente em `exited` ou `created` recebe `start()`.
Alternativas: recriar com `provision_system` (pega imagem/config atuais, mas perde a camada gravável
e é mais lento) e religar-ou-recriar conforme a imagem (mais lógica, e a troca de imagem não é
específica de container parado). Religar é o que o próprio restart policy faria; decisão do usuário.
Outros estados (`running`, `restarting`, `paused`, `removing`) ficam como estão; `dead` não aceita
`start`, o erro sobe como falha inesperada daquele sistema (log, estado intocado, próxima passada
tenta de novo — comportamento já especificado).

**D2 — Ordem: sistema primeiro, sidecars depois.** Se a reconciliação religou o container do
sistema, cada sidecar presente recebe `restart()` (que também liga um sidecar parado), porque um
sidecar que ficou rodando está preso à rede antiga. Com o container do sistema já rodando, só o
sidecar parado recebe `start()`; um rodando não é tocado. Sidecar ausente continua sendo recriado
como hoje.

**D3 — Estado do sistema fica com o monitor de saúde.** Ao religar, a reconciliação não chama
`set_status`. O sistema estava em erro "app fora do ar"; o monitor de saúde já sonda esses sistemas
e volta para ativo quando a app responde. Marcar ativo na hora do `start` diria "ativo" para uma app
que pode cair de novo ao subir. (A recriação continua marcando ativo, como no design D5 de
`portal-reconcile-loop`, porque ela também limpa erros de "reconciliação falhou".)

**D4 — Dono antes de religar.** A checagem de dono (`owner_description`) continua vindo antes de
qualquer ação: container com nome de outra instalação não é religado. Os sidecars já são
procurados pelo nome do sistema deste portal; os rótulos deles seguem o mesmo dono.

## Risks / Trade-offs

- [App que cai logo ao subir é religada a cada passada] → o custo é um `start` por intervalo; o
  sistema segue em erro pelo monitor de saúde, visível ao admin, como hoje.
- [Container antigo volta com imagem base velha] → aceito (D1); troca de imagem fica para outra
  mudança.
- [`restart()` de sidecar derruba conexões em curso do gate/proxy] → só acontece quando o container
  do sistema acabou de ser religado, ou seja, quando essas conexões já estavam quebradas.
