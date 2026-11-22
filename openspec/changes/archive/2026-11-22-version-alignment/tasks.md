# Tasks

## 1. Versão no portal

- [x] 1.1 Ler `__version__` dos metadados do pacote, com `"0+desconhecida"` sem eles (design D1). Subir o `pyproject.toml` para `1.11.0` e rodar `uv lock`. Verificar com:
  - `uv run python -c "import appaiforge; print(appaiforge.__version__)"`, que imprime `1.11.0`;
  - os testes de observabilidade do serviço, que conferem `service.version`, verdes.
- [x] 1.2 Derivar `base_image` e `claude_code_image` de `__version__` em `config.py` (design D2). Trocar os `0.1.0` fixos dos testes (`test_agent_profiles.py` e a imagem base padrão dos testes de integração) pela versão do pacote. Verificar com `uv run pytest tests/unit/test_agent_profiles.py` verde. Um teste confere que `APPAIFORGE_BASE_IMAGE` continua prevalecendo.

## 2. Chart e documentação

- [x] 2.1 `Chart.yaml` (`version` e `appVersion`) e `image.tag` em `values.yaml` e `values-production.yaml` em `1.11.0`, com os comentários das imagens padrão (design D3). Verificar com:
  - `helm template` padrão, que mostra a imagem `appaiforge/portal:1.11.0`;
  - `uv run pytest tests/unit/test_helm_chart.py` verde.
- [x] 2.2 Trocar as referências `0.1.0` às imagens da plataforma em `README.md`, no README do chart, em `docs/operacao.md`, `docs/configuracao.md`, `docs/driver-kubernetes.md` e `deploy/pilot-k8s/README.md`. Em `docs/operacao.md`, acrescentar o procedimento de release e a reconstrução das imagens (design D6). Verificar com um `grep` que não sobra `appaiforge/(portal|base|claude-code):0.1.0` fora de `openspec/changes/archive` e de `docs/roadmap-*`.
- [x] 2.3 Teste de alinhamento (design D5) em `portal/tests/unit/`. Verificar que:
  - passa;
  - falha ao trocar, num rascunho, só o `appVersion` ou uma tag num doc. Desfazer depois.

## 3. Verificação

- [x] 3.1 Construir `appaiforge/base:1.11.0` e `appaiforge/claude-code:1.11.0` no host. Rodar os testes de integração que sobem a imagem base. Num sistema descartável no compose, nunca nos sistemas existentes, confirmar que:
  - o container novo usa `appaiforge/base:1.11.0`;
  - o `/health` do portal informa `1.11.0`.

  Remover o sistema depois. Verificar também a suíte unitária inteira verde.

- Resultado da verificação:
  - `appaiforge/base:1.11.0` e `appaiforge/claude-code:1.11.0` construídas no host. A base reaproveitou o cache e tem o mesmo conteúdo da `0.1.0`.
  - Os testes de integração de provisionamento (`test_provisioning.py` e `test_claude_code_provisioning.py`) passam, 21 de 21, e conferem a imagem do container contra a do perfil.
  - No compose `aidb-ver` (projeto próprio, já desmontado com os volumes):
    - `/api/health` devolveu `{"status":"ok","version":"1.11.0"}`;
    - o sistema descartável `versao-teste` ficou ativo, com o container e o sidecar em `appaiforge/base:1.11.0`.

    O sistema e as pastas dele foram removidos, e os outros workspaces não foram tocados.
  - A suíte unitária inteira passa, 716 de 716.

## Workflow follow-up

- Arquivar a change (sincronizando `portal-installation`) na mesma branch, antes de abrir a PR. Depois, PR, merge e release v1.11.0. As notas de release devem trazer a reconstrução das imagens, no Docker e no Kubernetes.
