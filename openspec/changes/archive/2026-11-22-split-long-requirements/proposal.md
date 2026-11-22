# Proposal

## Why

Três specs falham no `openspec validate --strict` por um único motivo. Quatro requisitos passam de 500 caracteres e juntam vários comportamentos num parágrafo:
- dois em `app-serving`;
- um em `container-lifecycle`;
- um em `destructive-gate`.

Assim, o `--all --strict` nunca fica verde, e uma regressão real numa spec se esconde entre essas falhas conhecidas.

## What Changes

- **Cada requisito longo fica com um comportamento só.** Ele mantém o nome e todos os cenários. As outras frases normativas saem dele para requisitos novos, palavra por palavra (só "Ela" vira "A reconciliação", onde a frase perderia o sujeito):
  - `app-serving`:
    - "Acesso restrito a usuários com acesso ao sistema" fica com a verificação e a recusa. Ganha os vizinhos "Login a partir do link da app" e "Fim da sessão e do acesso alcança a app".
    - "Identidade do usuário propagada à app" fica com a emissão da identidade. Ganha "Identidade validada pela app" e "Identidade do cliente não chega à app".
  - `container-lifecycle`: "Containers ativos e reconciliados" fica com a reconciliação na subida e periódica. Ganha "Reconciliação respeita o estado atual do sistema" e "Falha da reconciliação isolada por sistema".
  - `destructive-gate`: "Gate do agente sobre SQL destrutivo" fica com a interceptação e a resposta automática. Ganha "Recusa do gate visível no chat".
- **Cada requisito novo tem um cenário próprio**, tirado só do texto normativo que já existia, sem comportamento novo. O de "Falha da reconciliação isolada por sistema" cobre a falha ao recriar um container, que estava no texto e não tinha cenário.
- **Nenhum comportamento muda**, e nenhum código é tocado.
- **O cenário "Agente pede DELETE em massa e o editor decide"**, de `destructive-gate`, continua com esse nome. O nome contradiz o corpo dele e o ADR 0023, mas renomear um cenário conta como removê-lo de um requisito modificado. Fica para uma edição à parte, se o operador quiser.

## Capabilities

### New Capabilities

(nenhuma)

### Modified Capabilities

- `app-serving`: dois requisitos com o texto reduzido, e quatro requisitos novos.
- `container-lifecycle`: um requisito com o texto reduzido, e dois requisitos novos.
- `destructive-gate`: um requisito com o texto reduzido, e um requisito novo.

## Impact

- **Arquivos:** só `openspec/specs/app-serving`, `container-lifecycle` e `destructive-gate`, na sincronização do arquivamento.
- **Código, testes e docs:** nada muda. Nenhum arquivo fora de `openspec/` cita os nomes desses requisitos.
- **Validação:** depois do arquivamento, `openspec validate --all --strict` fica verde, com 29 de 29 specs.
