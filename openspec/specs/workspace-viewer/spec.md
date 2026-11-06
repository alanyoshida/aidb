# workspace-viewer Specification

## Purpose

Permite que editores com acesso de gestão a um sistema naveguem pelos arquivos que o agente gerou no workspace e leiam seu conteúdo com destaque de sintaxe, sem sair do portal e sem risco de alterar o que foi gerado.

## Requirements

### Requirement: Aba Editor na página do sistema
A página do sistema SHALL ter uma aba "Editor" ao lado da aba Chat, visível exatamente para os usuários que veem as demais abas de gestão do sistema (Chat, Conexões, Checkpoints, Configurações, Auditoria).

#### Scenario: Editor visível para quem gerencia o sistema
- **WHEN** o dono do sistema ou um admin abre a página do sistema
- **THEN** a aba Editor aparece ao lado da aba Chat

#### Scenario: Editor ausente para quem não gerencia
- **WHEN** um usuário sem permissão de gestão sobre o sistema abre a página do sistema
- **THEN** a aba Editor não aparece, da mesma forma que as demais abas de gestão não aparecem

### Requirement: Árvore de arquivos do projeto gerado
Ao abrir a aba Editor, o portal SHALL listar em uma árvore, à esquerda, os arquivos da pasta onde o agente gera o projeto do sistema, refletindo o estado atual do workspace — não um checkpoint específico — e SHALL omitir artefatos técnicos (ambiente virtual, cache de bytecode, caches de execução da app) que não fazem parte do código gerado.

#### Scenario: Árvore reflete os arquivos gerados
- **WHEN** o agente já gerou a app do sistema
- **THEN** a árvore mostra os arquivos e diretórios da pasta do projeto, em estrutura hierárquica

#### Scenario: Diretórios técnicos ficam de fora
- **WHEN** a pasta do projeto contém ambiente virtual ou cache de bytecode
- **THEN** esses diretórios não aparecem na árvore

#### Scenario: Projeto ainda não gerado
- **WHEN** o agente ainda não gerou nenhum arquivo para o sistema
- **THEN** a aba Editor informa que não há arquivos ainda, em vez de mostrar uma árvore vazia sem explicação

### Requirement: Leitura de arquivo com destaque de sintaxe
Ao selecionar um arquivo na árvore, o portal SHALL exibir seu conteúdo no painel à direita com destaque de sintaxe apropriado à linguagem do arquivo, inferida pela extensão.

#### Scenario: Arquivo Python destacado
- **WHEN** o editor seleciona um arquivo `.py` na árvore
- **THEN** o conteúdo aparece no painel à direita com destaque de sintaxe Python

#### Scenario: Troca de arquivo atualiza o painel
- **WHEN** o editor seleciona um arquivo diferente do atualmente aberto
- **THEN** o painel à direita passa a mostrar o conteúdo e o destaque de sintaxe do novo arquivo selecionado

#### Scenario: Extensão desconhecida não quebra a visualização
- **WHEN** o editor seleciona um arquivo cuja extensão não tem linguagem mapeada
- **THEN** o conteúdo é exibido sem destaque de sintaxe, sem erro

#### Scenario: Arquivo binário ou ilegível como texto
- **WHEN** o editor seleciona um arquivo que não pode ser decodificado como texto
- **THEN** o portal exibe um aviso de que a pré-visualização não está disponível para esse arquivo, em vez de exibir conteúdo corrompido ou falhar

### Requirement: Conteúdo somente leitura
O painel de conteúdo SHALL impedir qualquer edição do texto exibido, e nenhuma ação da aba Editor SHALL gravar no workspace do sistema.

#### Scenario: Tentativa de digitar no painel é ignorada
- **WHEN** o editor clica no painel de conteúdo e tenta digitar
- **THEN** o conteúdo exibido permanece inalterado

#### Scenario: Nenhuma escrita no workspace
- **WHEN** o editor navega e abre arquivos na aba Editor
- **THEN** nenhum arquivo do workspace do sistema é criado, alterado ou removido como efeito dessa navegação

### Requirement: Atualização após execução do agente
Enquanto a aba Editor estiver aberta, o portal SHALL atualizar a árvore de arquivos quando uma execução do agente for concluída, sem exigir que o editor saia e volte à aba.

#### Scenario: Novo arquivo aparece após a geração
- **WHEN** o agente conclui uma execução que cria um arquivo novo, com a aba Editor aberta
- **THEN** o arquivo novo passa a aparecer na árvore sem o editor precisar recarregar a página
