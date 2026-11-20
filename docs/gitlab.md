# Preparar um projeto no GitLab

← [README](../README.md) · [Guia de uso](guia-de-uso.md)

Como preparar o projeto do GitLab de um sistema para o fluxo
`homolog → merge request (revisão + pipelines) → main → tag → produção`
([ADR 0029](adr/0029-repositorio-remoto-por-retransmissao-no-portal.md)). Os comportamentos abaixo
foram verificados no GitLab CE 19.4.

## 1. Pipeline num projeto separado

Crie um projeto de modelos de CI (por exemplo `time/ci-templates`) com o arquivo do pipeline
(validação, SAST, SCA etc. e, na `main`, o job que cria a tag de versão). No projeto do sistema,
aponte **Settings › CI/CD › General pipelines › CI/CD configuration file** para
`pipeline.yml@time/ci-templates`.

Assim o agente, que edita o repositório do sistema, não altera o pipeline. O AIDB também nunca envia
um `.gitlab-ci.yml` criado ou alterado no workspace.

## 2. Projeto do sistema vazio

Crie o projeto **sem README**. O AIDB recusa vincular uma branch de trabalho que já tenha histórico
sem relação com o do sistema.

## 3. Branches protegidas e merge

Em **Settings › Repository › Protected branches**, por nome (vale antes de a branch existir):

| Branch | Allowed to push and merge | Allowed to merge |
|---|---|---|
| `main` (destino) | No one | Developers + Maintainers |
| `homolog` (trabalho) | Maintainers | Developers + Maintainers |

Em **Settings › Merge requests**: método **Merge commit** (sem squash) e **Pipelines must succeed**.
Squash faria a branch de trabalho divergir da de destino a cada promoção. Proteja também as tags
`v*` (**Protected tags**) para que só o pipeline as crie.

No GitLab Free a aprovação de merge request é opcional; a garantia de revisão é a `main` protegida.

## 4. Chave de implantação

Na aba **Repositório** do sistema, copie a chave pública e cadastre-a em **Settings › Repository ›
Deploy keys** com **Grant write permissions**. Quem cadastra importa:

- O GitLab trata o push como sendo de quem cadastrou a chave. Cadastre com alguém que pode empurrar
  na `homolog` (Maintainer) — o push na `homolog` é aceito e na `main` é recusado.
- Push, merge request e pipeline aparecem em nome dessa pessoa; os commits continuam com o editor do
  AIDB como autor.

## 5. Token de API (opcional, para a promoção)

Em **Settings › Access tokens**, crie um token de projeto com papel **Developer** e escopo **api** e
cadastre-o na aba **Repositório** ("Testar token" confere o acesso). Sem token, "Solicitar promoção"
mostra o link de criação do merge request já preenchido.

## 6. Primeiro envio e a `main`

Na aba **Repositório**: salve o endereço SSH, **Testar conexão** (confira a impressão digital do
servidor), **Ativar vínculo**. O primeiro envio cria a `homolog`. Crie então a `main` a partir da
`homolog` e marque-a como branch padrão — a partir daí as promoções seguem por merge request.
