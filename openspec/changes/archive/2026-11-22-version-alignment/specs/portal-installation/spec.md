# Spec Delta

## ADDED Requirements

### Requirement: Versão única da instalação
O portal, o chart e as imagens padrão dos sistemas SHALL levar a mesma versão, igual à da release que os publicou. O portal SHALL informar essa versão no endpoint de saúde e na telemetria, salvo quando o operador a define por `OTEL_RESOURCE_ATTRIBUTES`. Sem imagem configurada pelo operador, os sistemas SHALL usar as imagens da plataforma com a tag dessa versão. Uma imagem configurada pelo operador SHALL prevalecer.

#### Scenario: Versão no endpoint de saúde
- **WHEN** o operador consulta o endpoint de saúde de um portal da release 1.11.0
- **THEN** a resposta informa a versão `1.11.0`

#### Scenario: Chart da mesma release
- **WHEN** o operador instala o chart da release 1.11.0 sem definir a tag da imagem do portal
- **THEN** o portal sobe com a imagem de tag `1.11.0`, e a telemetria dele chega com `service.version=1.11.0`

#### Scenario: Imagem padrão de um sistema novo
- **WHEN** um sistema é criado num portal da release 1.11.0 sem imagem de sistema configurada
- **THEN** o container do sistema usa `appaiforge/base:1.11.0`, ou `appaiforge/claude-code:1.11.0` com o perfil de agente `claude-code`

#### Scenario: Imagem fixada pelo operador
- **WHEN** o operador configura a imagem base dos sistemas com uma tag própria
- **THEN** os sistemas usam essa imagem, qualquer que seja a versão do portal
