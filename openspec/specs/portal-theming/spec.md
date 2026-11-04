# portal-theming Specification

## Purpose

Define a aparência do portal — modos claro, escuro e pastel, cores de destaque, preferência por usuário e as garantias de legibilidade que todas essas combinações devem cumprir.

## Requirements

### Requirement: Modos e cores de destaque selecionáveis
O portal SHALL oferecer três modos de aparência (claro, escuro e pastel) e quatro cores de destaque, combináveis livremente, selecionáveis a partir da barra superior em qualquer página autenticada.

#### Scenario: Troca de modo
- **WHEN** o usuário escolhe outro modo no seletor de aparência
- **THEN** o portal inteiro passa a usar esse modo, incluindo cabeçalho, cartões, abas, formulários, tabelas e chat

#### Scenario: Troca de cor de destaque
- **WHEN** o usuário escolhe outra cor de destaque
- **THEN** os elementos de destaque do portal — botões primários, abas ativas, links e a bolha das mensagens do próprio usuário — passam a usar essa cor, mantendo o modo atual

#### Scenario: Seletor disponível em todas as páginas
- **WHEN** o usuário navega para qualquer página autenticada do portal
- **THEN** o seletor de aparência está presente na barra superior, indicando o modo e a cor atualmente em uso

### Requirement: Preferência de tema persistida por usuário
O portal SHALL gravar a escolha de aparência no perfil do usuário e reaplicá-la em acessos futuros, inclusive de outro navegador ou dispositivo.

#### Scenario: Preferência sobrevive a novo acesso
- **WHEN** o usuário escolhe um tema, encerra a sessão e entra novamente
- **THEN** o portal apresenta o tema escolhido, sem voltar ao padrão

#### Scenario: Preferência é por usuário
- **WHEN** dois usuários distintos escolhem temas diferentes
- **THEN** cada um vê o próprio tema, sem que a escolha de um afete o outro

#### Scenario: Usuário sem preferência registrada
- **WHEN** um usuário que nunca escolheu um tema abre o portal
- **THEN** o portal apresenta o tema padrão, sem erro

### Requirement: Tema aplicado sem flash de cor incorreta
O portal SHALL entregar as cores do tema do usuário já na carga inicial da página, de modo que nenhum conteúdo seja exibido com as cores padrão antes de o tema ser aplicado.

#### Scenario: Carga direta de uma página
- **WHEN** o usuário abre uma página autenticada do portal
- **THEN** o conteúdo aparece já com as cores do tema escolhido, sem exibir outro tema momentaneamente

### Requirement: Contraste mínimo garantido em todas as combinações
O portal SHALL manter, em todas as combinações de modo e cor de destaque, contraste de pelo menos 4.5:1 entre texto e o fundo sobre o qual ele é exibido, e de pelo menos 3:1 para texto grande, conforme WCAG AA.

#### Scenario: Texto sobre superfícies do tema
- **WHEN** qualquer combinação de modo e cor de destaque está ativa
- **THEN** o texto principal e o texto secundário atingem o contraste mínimo contra o fundo da página e contra a superfície dos cartões

#### Scenario: Texto sobre preenchimentos coloridos
- **WHEN** um elemento é preenchido com a cor de destaque ou com uma cor semântica de sucesso, erro ou alerta
- **THEN** o texto exibido sobre esse preenchimento atinge o contraste mínimo, mesmo quando o preenchimento é um tom claro

#### Scenario: Avisos e notificações
- **WHEN** o portal exibe uma notificação, um aviso de erro ou o aviso de conexão perdida
- **THEN** o texto desses elementos atinge o contraste mínimo contra o próprio fundo deles, em qualquer modo

### Requirement: Significado preservado pelas cores semânticas
O portal SHALL manter a distinção visual entre estados de sucesso, erro, alerta e neutro em todos os modos, sem depender de tons fixos que ignorem o tema.

#### Scenario: Estados distinguíveis no modo escuro
- **WHEN** o modo escuro está ativo e a interface exibe estados de sucesso, erro e alerta
- **THEN** cada estado permanece distinguível dos demais e legível, em vez de usar o tom fixo que o componente traria por padrão
