# Proposal

## Why

O código que o agente gera vive só no volume de workspace do portal: não passa por revisão humana, não roda em pipeline de validação (SAST, SCA) e não tem como chegar a um portal de produção isolado. O ADR 0009 deixou o envio para um repositório remoto como opção futura; esta change a entrega para o portal de homologação, que é o primeiro passo do fluxo `homolog -> merge request -> main -> tag -> produção`.

Depende da change `isolate-workspace-repository`, que tira o repositório git do alcance do agente e torna o rollback não destrutivo. Sem ela, uma chave de repositório ficaria perto de operações git que executam conteúdo do workspace, e o rollback exigiria reescrever histórico já publicado.

## What Changes

- Nova aba "Repositório" na página do sistema: URL do repositório remoto (SSH), branch de trabalho (padrão `homolog`), branch de destino (padrão `main`), chave pública de implantação gerada pelo portal, confirmação da identidade do servidor e teste de conexão.
- Cada checkpoint é enviado à branch de trabalho do repositório remoto. A chave privada fica cifrada no portal e nunca entra no container do sistema; o envio parte do portal.
- Antes de cada execução do agente, o portal traz para o workspace o que foi mergeado na branch de trabalho por fora (merge requests de humanos).
- Quando há alterações sem checkpoint no workspace e commits a trazer do remoto, a execução não começa: o editor decide entre salvar e descartar.
- Quando o que veio do remoto conflita com o trabalho local, o sistema fica em estado "divergente": o portal para e mostra os arquivos em conflito. As saídas são resolver o conflito no workspace, por ação explícita, ou adotar a versão do remoto.
- Ação explícita "Solicitar promoção" abre o merge request da branch de trabalho para a branch de destino pela API do GitLab, com um token opcional por sistema guardado cifrado no portal; sem token, o portal mostra o endereço de criação já preenchido. Nenhum merge request é aberto automaticamente.
- O portal não envia ao remoto alterações feitas no workspace em `.gitlab-ci.yml` na raiz do repositório.
- Novo stack de E2E com GitLab local e GitLab Runner, montado no início do trabalho para verificar o comportamento do GitLab antes de implementar sobre ele, e nova fixture de integração com servidor git por SSH.

Fora desta change: o sistema "só implantação" do portal de produção (deploy por tag, trava por instalação, manifesto de conexões), status de pipeline no portal, forjas diferentes de GitLab, e mudança de schema no banco de produção.

## Capabilities

### New Capabilities

- `system-git-remote`: vínculo de um sistema com um repositório remoto — configuração, chave de implantação, envio de checkpoints, sincronização da branch de trabalho, estado divergente e solicitação de promoção.

### Modified Capabilities

Nenhuma. O requisito de checkpoints de `agent-harness` é alterado pela change `isolate-workspace-repository`.

## Impact

- **Código do portal**: `checkpoints.py` e o backend git por driver (pacotes, integração), `agent_queue.py` (sincronização antes da execução, envio depois do checkpoint), `ui/system_detail.py` (nova aba), `models.py` e migração Alembic (vínculo com o remoto), `provisioning.py` (exclusão definitiva), `config.py`.
- **Imagem do portal**: passa a precisar do cliente SSH. O portal passa a abrir conexão de saída para o servidor git configurado; a rede do agente não muda.
- **Deploy**: novo volume do portal para as cópias de retransmissão; chart Helm atualizado.
- **Testes**: cenários BDD da capability, testes de integração com servidor git por SSH, e a suíte `tests/e2e_gitlab` contra `deploy/docker-compose.e2e-gitlab.yml` (GitLab CE e runner com versão fixada; exige vários GB de memória e não roda junto com as outras suítes E2E).
- **Documentação**: ADR do repositório remoto, `docs/seguranca.md`, `docs/testes.md`, `docs/guia-de-uso.md` e um guia de preparação do projeto no GitLab (chave de implantação, branches protegidas, merge sem squash, pipeline em projeto separado).
