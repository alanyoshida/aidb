# Tasks

## 1. Driver Docker religa container parado

- [x] 1.1 Testes unitários (cliente Docker falso) para `DockerProvisioningDriver.reconcile_one`: container do sistema `exited` recebe `start` e os sidecars presentes recebem `restart` depois dele; sistema rodando com sidecar `exited` recebe só `start` no sidecar; sistema e sidecars rodando não recebem nada; container de outro dono não é religado. Verificar que falham antes da implementação.
- [x] 1.2 Implementar em `reconcile_one` e nos `_reconcile_*_sidecar` (D1, D2, D4) e verificar que os testes de 1.1 passam.
- [x] 1.3 Teste de integração em `portal/tests/integration/test_provisioning.py`: `docker stop` no container do sistema e no sidecar, `reconcile()`, e os dois voltam a `running` com o mesmo id e o sidecar no namespace de rede do sistema; verificar rodando a suíte de integração.

## 2. Documentação

- [x] 2.1 Atualizar a docstring de `reconcile()` em `portal/appaiforge/provisioning.py` com o caso "unidade presente e parada" e verificar lendo a docstring.

## 3. Verificação

- [x] 3.1 Rodar a suíte unitária e a de integração do portal e verificar que passam.
- [x] 3.2 Rodar `detect_changes` do GitNexus e verificar que só os fluxos de reconciliação aparecem afetados.

## Workflow follow-up

- Arquivar a change (`openspec archive`) antes de abrir o PR.
- Abrir o PR com o código e a change arquivada.
