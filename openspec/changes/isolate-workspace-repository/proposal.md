# Proposal

## Why

O portal executa `git` dentro de `/workspace/.git`, um diretório que o agente pode escrever. Hooks, filtros de `.gitattributes`, `core.fsmonitor` e outras configurações plantadas ali seriam executados no processo do portal como root (driver Docker) ou por `exec` fora do confinamento do agente (driver Kubernetes). Não há nenhuma neutralização hoje. Isso é um caminho de fuga do confinamento que existe independentemente de qualquer funcionalidade nova, e é pré-requisito para a change `add-system-git-remote`, que coloca uma chave de repositório perto dessas operações.

## What Changes

- O repositório git de cada sistema sai do workspace. O workspace passa a ser só a árvore de trabalho; objetos, referências, configuração e hooks ficam em local que o agente e a app gerada não alcançam, nos drivers Docker e Kubernetes.
- As operações git do portal deixam de carregar qualquer hook, configuração, filtro ou driver vindo do workspace.
- O histórico de checkpoints dos sistemas existentes é levado para o novo local sem perder checkpoints nem mudar seus identificadores.
- **BREAKING** O rollback de checkpoint deixa de reescrever o histórico (`git reset --hard`) e passa a criar um checkpoint novo que restaura o estado escolhido. O estado do workspace após o rollback é o mesmo de hoje; os checkpoints posteriores continuam no histórico.
- A exclusão definitiva de um sistema remove também o repositório.

Fora desta change: repositório remoto, chave de implantação, sincronização e promoção (change `add-system-git-remote`, que depende desta).

## Capabilities

### New Capabilities

- `workspace-repository`: onde vive o repositório git de cada sistema e a garantia de que nada controlado pelo workspace executa durante as operações git do portal.

### Modified Capabilities

- `agent-harness`: o requisito "Checkpoints git por execução" muda — o rollback preserva o histórico e é registrado como um checkpoint novo.

## Impact

- **Código do portal**: `checkpoints.py` (todas as operações git), `provisioning.py` e os dois drivers (local do repositório, exclusão definitiva), `ui/system_detail.py` (aba Checkpoints), `models.py` e migração Alembic (origem do checkpoint), `config.py` (novo diretório de repositórios).
- **Driver Kubernetes**: novo container auxiliar de git no pod do sistema e um volume próprio para o repositório; pods existentes são recriados pela reconciliação.
- **Deploy**: novo volume montado só no portal no driver Docker; chart Helm atualizado.
- **Dados existentes**: migração preguiçosa do histórico, na primeira operação git de cada sistema. O `.git` antigo permanece no workspace, sem uso pelo portal.
- **Testes**: novos cenários BDD, testes de integração de isolamento e extensão da suíte de paridade entre drivers.
- **Documentação**: ADR novo substituindo a parte de rollback do ADR 0009, `docs/seguranca.md`, `docs/driver-kubernetes.md`.
