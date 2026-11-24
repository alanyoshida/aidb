# Spec Delta

## ADDED Requirements

### Requirement: Modos de acesso disponíveis para BigQuery
O portal SHALL limitar o teto de modo de acesso das autorizações de conexões BigQuery a `read_only` e `read_write`, e SHALL NOT oferecer `schema_admin` para elas.

#### Scenario: schema_admin indisponível
- **WHEN** um DB Manager define o teto da autorização de uma conexão BigQuery
- **THEN** as opções são `read_only` e `read_write`, sem `schema_admin`

#### Scenario: Tentativa direta é recusada
- **WHEN** alguém tenta gravar o teto `schema_admin` numa autorização de conexão BigQuery
- **THEN** o portal recusa informando que o modo não se aplica a BigQuery

### Requirement: Aviso de rotação de chave ao revogar BigQuery
Ao revogar a autorização de uma conexão BigQuery ativa, ou excluí-la do catálogo com autorizações ativas, o portal SHALL cessar a entrega da credencial ao sistema na hora e SHALL avisar quem executou a ação de que uma chave já entregue à app só é invalidada de vez ao ser rotacionada no GCP.

#### Scenario: Revogação com aviso
- **WHEN** um DB Manager revoga a autorização de uma conexão BigQuery ativa no sistema X
- **THEN** a app e o agente de X deixam de receber a credencial, e o DB Manager vê o aviso de que a chave da Service Account precisa ser rotacionada no GCP para invalidar cópias já lidas

#### Scenario: Revogação de conexão nunca ativada
- **WHEN** um DB Manager revoga a autorização de uma conexão BigQuery que nunca foi ativada no sistema
- **THEN** o portal não exibe o aviso de rotação

### Requirement: Cadastro de conexão BigQuery no catálogo

O portal SHALL permitir que quem gere o catálogo cadastre uma conexão BigQuery informando nome, GCP project ID, dataset e Service Account JSON; o campo de senha convencional NÃO é exibido para conexões BigQuery.

#### Scenario: DB Manager cadastra conexão BigQuery com credencial válida
- **WHEN** um DB Manager informa project ID, dataset e um Service Account JSON com acesso ao dataset
- **THEN** o portal confirma o cadastro após teste bem-sucedido
- **AND** exibe o service account email (extraído do JSON) como identificador da credencial

#### Scenario: Service Account JSON inválido é recusado
- **WHEN** um DB Manager informa um JSON malformado ou sem permissão no dataset
- **THEN** o portal recusa o cadastro informando que o teste de conexão falhou

## MODIFIED Requirements

### Requirement: Service Account JSON protegido como credencial sensível

O portal SHALL armazenar o Service Account JSON cifrado em repouso e nunca retorná-lo na interface, em logs ou em eventos do agente; apenas o service account email é exibido, e somente a quem gere o catálogo.

#### Scenario: Edição não revela o JSON
- **WHEN** um DB Manager abre uma conexão BigQuery do catálogo para edição
- **THEN** o campo de Service Account JSON não retorna o conteúdo salvo

#### Scenario: Dono não vê o service account email
- **WHEN** o dono de um sistema abre a aba de conexões com uma conexão BigQuery autorizada
- **THEN** a conexão não exibe o service account email, o project ID nem o dataset

### Requirement: Provisão à app gerada via DATABASE_URL com credentials_base64

O portal SHALL disponibilizar cada conexão BigQuery ativa no sistema à app gerada como variável de ambiente `DATABASE_URL_<ALIAS>` no formato `bigquery://<project>/<dataset>?credentials_base64=<b64>`, compatível com `sqlalchemy-bigquery`.

#### Scenario: App gerada conecta ao BigQuery
- **WHEN** a app gerada inicia no container do sistema com uma conexão BigQuery ativa
- **THEN** recebe `DATABASE_URL_<ALIAS>=bigquery://<project>/<dataset>?credentials_base64=...`
- **AND** consegue conectar ao dataset usando `sqlalchemy-bigquery` com essa URL

## REMOVED Requirements

### Requirement: Cadastro de conexão BigQuery via Service Account JSON
**Reason**: O cadastro de conexões BigQuery deixa de ser feito pelo dono do sistema e passa a ser feito no catálogo por quem o gere.
**Migration**: Use "Cadastro de conexão BigQuery no catálogo". Os campos e a validação são os mesmos; as conexões BigQuery existentes são convertidas em conexões do catálogo já autorizadas e ativas no sistema de origem.
