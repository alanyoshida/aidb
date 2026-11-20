# 0029 — Repositório remoto do sistema: envio pelo portal, chave e token fora do container

* Status: aceito
* Data: 2026-11-21
* Decidida em: change `add-system-git-remote` (design D1, D2, D7)
* Retoma: a opção futura "push automático para GitHub/GitLab" do [0009](0009-git-por-sistema-com-checkpoints.md)

## Contexto

O código gerado precisa passar por merge request, revisão humana e pipelines (SAST, SCA) antes de
chegar à produção, que roda num portal separado. Para isso cada sistema do portal de homologação
envia seus checkpoints a uma branch de trabalho num GitLab. O [0028](0028-repositorio-git-do-sistema-fora-do-workspace.md)
já tirou o repositório do alcance do agente; esta decisão define como o portal fala com o remoto
sem que nenhum segredo chegue ao container do sistema.

## Decisão

1. **O portal envia, nunca o container.** Cada sistema tem uma cópia bare de retransmissão no
   portal (`APPAIFORGE_GIT_RELAYS_DIR/<slug>`). O repositório do sistema troca pacotes (`git bundle`)
   com ela, e só a retransmissão fala com o GitLab. Assim o mesmo caminho serve aos dois drivers, e
   o pod do Kubernetes (que divide rede com o agente) nunca precisa de chave nem de saída para o
   servidor git.
2. **Chave de implantação ed25519 por sistema**, gerada pelo portal e guardada cifrada. Ela vai
   para um diretório temporário (em `tmpfs` quando há) só durante a operação; o `ssh` roda com
   `-F /dev/null`, `known_hosts` temporário com a chave do servidor confirmada pelo editor, e o git
   só aceita o transporte SSH.
3. **Nada é reescrito no remoto.** Envio sem `--force`; se o remoto tem commits que o sistema ainda
   não integrou, o portal integra antes (avanço rápido ou merge) e, havendo conflito, para em estado
   "divergente". Alterações não salvas com commits a trazer bloqueiam a execução até o editor decidir.
4. **API do GitLab só para a promoção**, com um token opcional por sistema (cifrado, nunca exibido
   nem entregue ao container). A verificação contra o GitLab 19.4 mostrou que abrir merge request
   pela opção de push não funciona sem commit novo — o caso comum ao solicitar promoção —, então o
   portal consulta o MR aberto entre as branches e abre um quando não há. Sem token, mostra o link
   de criação preenchido.
5. **`.gitlab-ci.yml` do workspace nunca vai para o remoto.** O pipeline vem de um projeto separado
   (configuração do GitLab); o portal ainda exclui o arquivo novo e desfaz a alteração no rastreado.

## Alternativas consideradas

- **Push direto do repositório do sistema**: no Kubernetes exigiria chave no pod e saída de rede do
  pod para o servidor git, alcançável também pelo agente em modo não `sandboxed`.
- **Opção de push `merge_request.create` sem API**: descartada depois da verificação (ver item 4).
- **Último MR visto nas respostas de push / commit vazio de promoção**: sem segredo novo, mas sem
  saber se o MR ainda está aberto, ou poluindo o histórico a cada solicitação.

## Consequências

- O GitLab registra push, merge request e pipeline em nome de quem cadastrou a chave e o token; a
  garantia de revisão é a branch de destino protegida ("ninguém faz push").
- Um segundo segredo por sistema (o token), com rotação a cargo do time.
- A imagem do portal ganha `openssh-client`; o portal passa a abrir conexão de saída para o GitLab.
  A rede do agente não muda (verificado: o agente confinado não alcança o servidor git).
- O sistema "só implantação" do portal de produção fica para a change seguinte.
