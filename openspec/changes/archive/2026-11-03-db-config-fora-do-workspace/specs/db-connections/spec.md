# Spec Delta

## ADDED Requirements

### Requirement: Configuração do agente isolada do workspace
O portal SHALL gravar o arquivo de configuração do agente (incluindo as connection strings dos bancos) em um diretório separado, fora do workspace acessível ao agente, de forma que o conteúdo do workspace não exponha credenciais de banco de dados.

#### Scenario: opencode.json não está no workspace
- **WHEN** o agente lista ou lê os arquivos do workspace de um sistema com conexões cadastradas
- **THEN** o arquivo de configuração do agente (opencode.json) não está presente no workspace e as connection strings não são acessíveis por navegação de arquivos no workspace
