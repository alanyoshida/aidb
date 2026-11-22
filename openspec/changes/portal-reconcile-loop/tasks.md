# Tasks

## 1. Trava por sistema e reconciliação robusta (`provisioning.py`)

- [x] 1.1 Criar `system_operation_lock(system_id)` (RLock por sistema) e segurá-la em `provision_system`, `refresh_https_allowlist`, `archive_system` e `delete_system` (design D3); verificar com teste unitário que `provision_system` chamado de dentro da trava já segura não trava (reentrância) e que outra thread não consegue a trava enquanto `provision_system` roda.
- [x] 1.2 Em `reconcile()`: tentar a trava sem bloquear e pular o sistema ocupado; com a trava, reler o sistema e pular se sumiu, está `archived` ou `provisioning` (design D3); verificar com testes unitários: sistema com a trava ocupada não chega ao driver e é reconciliado na passada seguinte; sistema arquivado depois da leitura inicial não é recriado.
- [x] 1.3 Isolar falhas por sistema em `reconcile()` (erro inesperado só em log, estado inalterado, demais sistemas seguem, saúde das conexões ainda checada — design D4) e voltar a ativo sem mensagem um sistema recriado com sucesso (design D5); verificar com testes unitários: `reconcile_one` levantando `RuntimeError` num sistema não impede o outro e não muda o estado; recriação bem-sucedida de um sistema em erro o deixa ativo e sem mensagem.
- [x] 1.4 Atualizar a docstring de `reconcile()` (quando roda, trava, isolamento de falhas, efeitos nos dois drivers) e verificar que bate com o código revisado.

## 2. Laço de reconciliação na subida e periódico

- [x] 2.1 Adicionar `reconcile_interval: float = 300.0` em `config.py` e `start_reconcile_loop(interval=None, stop=None)` em `provisioning.py` (design D1/D2): passada imediata, depois uma a cada intervalo; `<= 0` faz só a primeira; exceção numa passada não encerra o laço; verificar com testes unitários (passada imediata, periódica com intervalo curto, intervalo zero faz uma só, exceção seguida de nova passada, `stop` encerra).
- [x] 2.2 Iniciar o laço em `main.create_app()` ao lado de `start_monitor()`/`start_poller()`; verificar com teste unitário que `create_app` inicia o laço (sem rodar a reconciliação de forma síncrona) e com `uv run pytest -n 8 tests/unit tests/bdd` verde.

## 3. Escrita de rota Docker idempotente (`edge.py`)

- [x] 3.1 `edge._write()` não reescreve o arquivo quando o conteúdo é igual ao atual (design D6); verificar com teste unitário que a segunda publicação igual não muda o `mtime`/inode do arquivo e que uma publicação diferente reescreve.

## 4. Integração e documentação

- [x] 4.1 Teste de integração com Docker real: com o laço rodando (intervalo curto), um container de sistema ativo removido por fora é recriado e o sistema fica ativo; verificar com `uv run pytest tests/integration/test_provisioning.py` verde (os testes Kubernetes, que usam o cluster `kind-appaiforge-dev`, só rodam com autorização do operador).
- [x] 4.2 Documentar `APPAIFORGE_RECONCILE_INTERVAL` em `docs/configuracao.md` (com o uso via `portal.extraEnv` no chart), quando a reconciliação roda em `docs/driver-kubernetes.md` e uma nota de implementação no ADR 0013; verificar que nenhuma doc ou docstring ainda diz que a reconciliação não roda no boot (`grep -rn "reconcil" docs portal/appaiforge`).

## Workflow follow-up

- Feito na integração com a change `gateway-api-traefik-subchart`: remover a chamada de `republish_routes()` da subida e a função, trocando o teste dela (design D7).
- Arquivar a change depois da revisão do PR.
