# Proposal

## Why

No driver Docker, a reconciliação só trata container de sistema **ausente** (recria) e sidecar
ausente (recria só ele). Um container que existe mas está **parado** — derrubado com `docker stop`,
morto por OOM ou pelo daemon (`Exited (137)`) — fica parado para sempre: com restart
`unless-stopped` o Docker não o religa depois de um `stop` explícito, e o health monitor só marca o
sistema como "app fora do ar (N checagens)". Isso apareceu num ambiente de dev com quatro sistemas
parados havia uma semana; um `docker start` manual resolveu na hora.

## What Changes

- Na reconciliação (driver Docker), container de sistema presente e parado é **religado**, não
  recriado: a imagem, a configuração e a camada gravável do container ficam como estavam.
- Quando a reconciliação religa o container do sistema, os sidecars presentes (gate de banco e
  proxy HTTP(S) de saída) são reiniciados **depois** dele — eles usam a rede do container do
  sistema e, se ficaram rodando, estão presos à rede antiga.
- Com o container do sistema rodando, sidecar presente e parado é religado.
- O sistema volta a ativo sozinho pelo monitor de saúde, quando a app responde; a reconciliação não
  muda o estado do sistema ao religar.
- Fora de escopo: trocar a imagem de containers antigos (vale também para os que estão rodando) e o
  driver Kubernetes (Pod parado já é tratado pelo próprio cluster).

## Capabilities

### New Capabilities

(nenhuma)

### Modified Capabilities

- `container-lifecycle`: o requisito "Containers ativos e reconciliados" passa a cobrir container
  presente e parado (religado pela reconciliação, junto com os sidecars).

## Impact

- `portal/appaiforge/drivers/docker_driver.py`: `reconcile_one` e os `_reconcile_*_sidecar`.
- `portal/appaiforge/provisioning.py`: docstring de `reconcile()`.
- Testes: unitários do driver Docker com cliente falso e integração com Docker real em
  `portal/tests/integration/test_provisioning.py`.
- Sem mudança de API, modelo de dados, configuração ou dependências.
