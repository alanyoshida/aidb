# 0030 — Sistema só implantação: produção implanta tags verificadas, sem agente

* Status: aceito
* Data: 2026-11-20
* Decidida em: change `add-deploy-only-system` (design D1, D2, D4, D5, D7, D8)
* Complementa: [0029](0029-repositorio-remoto-por-retransmissao-no-portal.md)

## Contexto

O portal de homologação envia o código de cada sistema a um GitLab, onde a mudança passa por merge
request, revisão e pipelines e vira uma tag de versão na branch de destino ([0029](0029-repositorio-remoto-por-retransmissao-no-portal.md)).
A produção é outra instalação do portal, com banco próprio, que só deve rodar essas versões
aprovadas. Ela não pode executar agente, não deve guardar credencial de LLM e não pode depender de
alguém lembrar de configurar isso sistema por sistema.

## Decisão

1. **Tipo por sistema, trava por instalação.** Cada sistema é "com agente" ou "só implantação",
   fixado na criação. Com `APPAIFORGE_INSTALLATION_ROLE=production`, o portal recusa criar e
   provisionar sistema com agente, inclusive na reconciliação. Um portal de desenvolvimento aceita
   os dois tipos.
2. **Container sem agente.** O sistema só implantação usa a mesma imagem base, mas sem config nem
   perfil de agente e sem credencial ou token de LLM. O supervisor sobe só a app, e a allow-list de
   saída fica só com os registros de pacote.
3. **Só implanta commit contido na branch de destino.** O portal lê o repositório pela cópia de
   retransmissão com uma chave só leitura e nunca escreve nele. Antes de implantar uma tag, confere
   que o commit dela é ancestral da ponta da branch de destino, que é protegida. Registra o commit
   verificado, não o nome da tag, porque uma tag pode ser movida.
4. **Dependências antes do código, saúde depois.** Quando o `uv.lock` muda, `uv sync --frozen` roda
   no container a partir de um diretório temporário, antes de o workspace trocar. Uma falha deixa
   tudo como estava. Depois da troca, a versão só conta como implantada quando a app reiniciada
   (o supervisor grava o PID dela) responde em três checagens seguidas dentro do prazo. Senão o
   portal volta à versão anterior e registra a volta. Rollback é implantar uma tag anterior.
5. **Automático só com tags nunca implantadas.** A tag mais nova do padrão só é implantada se nunca
   houve implantação dela no sistema, com qualquer resultado. Assim um rollback manual permanece até
   sair uma tag nova, e uma tag que falhou não é repetida. A detecção é por consulta periódica ou
   por webhook do GitLab. O webhook só dispara essa mesma verificação e ignora o corpo da chamada.
6. **Manifesto de conexões.** A cada checkpoint de um sistema com repositório ativo, a homologação
   grava `.aidb/manifest.json` só com o nome e o tipo de cada conexão. A produção recusa a versão
   que exige uma conexão não cadastrada com aquele nome.

## Alternativas consideradas

- **Só o papel da instalação, sem tipo por sistema**: impede testar o fluxo de produção num portal
  de desenvolvimento; descartada.
- **Implantar a tag pelo nome, sem verificar a branch**: qualquer tag empurrada por quem tem acesso
  iria para produção sem passar pelo merge request; descartada.
- **Implantar automaticamente sempre a tag mais nova**: desfaria um rollback manual na verificação
  seguinte; descartada.
- **Confiar no conteúdo do webhook**: um corpo forjado com o segredo vazado escolheria a versão;
  o webhook só agenda a verificação do repositório.

## Consequências

- Produção nunca executa agente, mesmo que um sistema com agente seja copiado para o banco dela.
- O GitLab precisa alcançar o portal de produção para o webhook; sem isso, a consulta periódica
  atende.
- Instalar dependências exige saída do container para o PyPI pela allow-list padrão. Com a internet
  desligada no sistema, só implanta versão com o mesmo lock.
- Mudança de schema do banco de produção continua fora do escopo: o manifesto só garante que as
  conexões existem.
