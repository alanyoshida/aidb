Feature: Vínculo do sistema com um repositório git remoto
  Como dono de um sistema
  Quero enviar os checkpoints a uma branch de trabalho num GitLab
  Para que as mudanças passem por merge request, revisão e pipelines
  # Fonte: specs/system-git-remote/spec.md (cenários de interface estão em tests/e2e_gitlab)

  Scenario: Branches com valor padrão
    Given um sistema com um checkpoint
    When o editor informa apenas o endereço do repositório
    Then a branch de trabalho fica "homolog" e a de destino fica "main"

  Scenario: Endereço que não é SSH
    Given um sistema com um checkpoint
    When o editor informa o endereço "https://gitlab.exemplo.com/time/app.git"
    Then a configuração é recusada explicando o formato aceito

  Scenario: Chaves diferentes por sistema
    Given dois sistemas com repositório configurado
    Then cada um tem uma chave pública diferente

  Scenario: Chave privada nunca exibida
    Given um sistema vinculado ao repositório remoto
    Then nenhuma resposta nem registro de auditoria contém a chave privada

  Scenario: Endereço da API derivado do repositório
    Given um sistema com um checkpoint
    When o editor informa o endereço "git@gitlab.exemplo.com:time/app.git" sem endereço de API
    Then o endereço da API usado é "https://gitlab.exemplo.com"

  Scenario: Chave do servidor mudou
    Given um sistema vinculado ao repositório remoto
    When o servidor passa a apresentar outra chave
    Then o envio é recusado porque a identidade do servidor mudou

  Scenario: Repositório remoto vazio
    Given um sistema com um checkpoint e o repositório configurado
    When o editor ativa o vínculo
    Then a branch de trabalho é criada no remoto com os checkpoints do sistema

  Scenario: Branch de trabalho com histórico não relacionado
    Given um sistema com um checkpoint e o repositório configurado
    And a branch de trabalho do remoto tem histórico próprio
    When o editor tenta ativar o vínculo
    Then o vínculo é recusado e o remoto não muda

  Scenario: Alteração pelo chat chega ao remoto
    Given um sistema vinculado ao repositório remoto
    When um novo checkpoint do editor é criado
    Then o commit aparece na branch de trabalho do remoto com o editor como autor

  Scenario: Remoto fora do ar
    Given um sistema vinculado ao repositório remoto
    When um novo checkpoint é criado com o remoto fora do ar
    Then o checkpoint existe e o repositório fica com envio pendente

  Scenario: Merge request de humano chega ao workspace
    Given um sistema vinculado ao repositório remoto
    And um merge request humano foi mergeado na branch de trabalho
    When o portal sincroniza antes de uma execução
    Then o workspace contém as alterações mergeadas
    And o histórico mostra um checkpoint vindo do repositório remoto

  Scenario: Execução bloqueada por sobras de execução interrompida
    Given um sistema vinculado ao repositório remoto
    And um merge request humano foi mergeado na branch de trabalho
    And o workspace tem alterações sem checkpoint
    When o portal sincroniza antes de uma execução
    Then a execução é impedida pedindo para salvar ou descartar as alterações

  Scenario: Conflito detectado
    Given um sistema vinculado ao repositório remoto
    And o remoto e o sistema alteraram a mesma linha
    Then o sistema fica divergente com o arquivo em conflito listado
    And o workspace não contém marcas de conflito

  Scenario: Remoto adotado
    Given um sistema vinculado ao repositório remoto
    And o remoto e o sistema alteraram a mesma linha
    When o editor adota a versão do remoto
    Then o workspace tem o conteúdo do remoto e o sistema deixa de estar divergente

  Scenario: Promoção indisponível com pendência
    Given um sistema vinculado ao repositório remoto
    And o remoto e o sistema alteraram a mesma linha
    When o editor solicita promoção
    Then a solicitação é recusada explicando o que resolver

  Scenario: Agente cria o arquivo de pipeline
    Given um sistema vinculado ao repositório remoto
    When o agente cria ".gitlab-ci.yml" e um checkpoint é criado
    Then o arquivo de pipeline não chega ao remoto

  Scenario: Vínculo desativado
    Given um sistema vinculado ao repositório remoto
    When o editor desativa o vínculo e um novo checkpoint é criado
    Then nada novo chega ao remoto

  # --- Manifesto de conexões pelo alias (change add-db-manager-role) ---

  Scenario: Manifesto acompanha o checkpoint
    Given um sistema vinculado ao repositório remoto
    And as conexões ativas "vendas" (postgres) e "estoque" (mysql) no sistema
    When um checkpoint é criado com o manifesto de conexões
    Then o manifesto no remoto lista "estoque" (mysql) e "vendas" (postgres)

  Scenario: Nenhuma credencial no manifesto
    Given um sistema vinculado ao repositório remoto
    And as conexões ativas "vendas" (postgres) e "estoque" (mysql) no sistema
    When um checkpoint é criado com o manifesto de conexões
    Then o manifesto no remoto não tem endereço, usuário nem nome do catálogo

  Scenario: Conexão não ativada fica fora
    Given um sistema vinculado ao repositório remoto
    And as conexões ativas "vendas" (postgres) e "estoque" (mysql) no sistema
    And a conexão "rascunho" autorizada e não ativada no sistema
    When um checkpoint é criado com o manifesto de conexões
    Then o manifesto no remoto lista "estoque" (mysql) e "vendas" (postgres)
