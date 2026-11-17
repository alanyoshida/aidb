# Guia de uso

← [README](../README.md)

## Criar um sistema (fluxo do usuário)

1. Login como **editor** → "Novo sistema" → nome + slug.
2. Aguarde o badge **ativo** (container provisionado, app em `/apps/<slug>` mostrando "ainda não gerada").
3. Na página do sistema: **Conexões** → escolha o tipo e cadastre o banco, testado antes de salvar (vira MCP somente leitura do agente + `DATABASE_URL_<NOME>` da app):
   - **PostgreSQL / MySQL**: host, porta, banco, usuário e senha.
   - **BigQuery**: projeto, dataset e JSON de Service Account (guardado cifrado).
   - Cada conexão tem um estado de saúde monitorado (ver [Operação](operacao.md)).
4. **Chat de geração**: peça em PT-BR ("crie um CRUD da tabela clientes com busca e formulário"). Acompanhe o streaming, interrompa se preciso (detalhes em *Chat* abaixo).
5. Ao concluir: checkpoint criado, app reiniciada e servida em `/apps/<slug>`; "Abrir app" entra com sua identidade (SSO por token HMAC).
6. **Checkpoints** → "Restaurar" para voltar o código a qualquer ponto (a app reinicia no estado restaurado).

## Chat

- **Sessões**: cada editor mantém várias sessões nomeadas por sistema (criadas na primeira mensagem, renomeáveis, com troca na lista). O agente mantém o contexto dentro da sessão; se o contexto for reiniciado (container recriado, sessão inválida) o chat avisa.
- **Mensagens**: data e hora ao lado do nome de quem enviou, no fuso `APPAIFORGE_DISPLAY_TIMEZONE`. Os marcadores de execução (iniciada, concluída, interrompida, erro) aparecem em português.
- **Disponibilidade**: abaixo do chat, uma bolinha verde indica agente livre e uma amarela pulsando indica trabalho em curso (sem animação se o sistema operacional pede movimento reduzido).
- **Debug**: comandos executados e arquivos alterados só aparecem com a chave **Debug** ligada; ligar e desligar não perde histórico.
- **Artifacts**: o agente pode responder com blocos ` ```echart `, ` ```table ` e ` ```html `, que o chat renderiza como gráfico, tabela interativa e HTML em sandbox.
- **Checkpoint manual**: o botão informa se criou um checkpoint ou se não havia alteração a salvar.
- **Comandos do agente (`/`)**: digitar `/` no início da mensagem abre a lista dos comandos que o agente daquele sistema reconhece, com descrição; o texto filtra a lista, setas navegam, Enter ou Tab completam o comando (sem enviar) e Esc fecha. Todo sistema vem com o OpenSpec 1.15.0 configurado no workspace (`openspec/` e `.opencode/`, artefatos em PT-BR): `/opsx-propose <descrição>` cria uma change com proposta, specs, design e tarefas; `/opsx-explore` ajuda a pensar antes de decidir; `/opsx-apply <change>` implementa; `/opsx-archive <change>` arquiva. Os arquivos da change entram no checkpoint da execução. Se o agente não responder à listagem, o chat só não mostra sugestões — a mensagem é enviada normalmente.

## Editor

Aba ao lado do Chat, visível para quem gerencia o sistema (mesmo acesso das demais abas). Mostra, à esquerda, a árvore de arquivos da pasta onde o agente gera o projeto (`<workspace>/app`, sem `.venv`/`__pycache__`/`.git`/caches do NiceGUI) e, à direita, o conteúdo do arquivo selecionado com destaque de sintaxe pela extensão. **Somente leitura**: o painel nunca aceita edição, e nada feito nessa aba grava no workspace. A árvore reflete o estado atual do workspace (não um checkpoint específico) e se atualiza sozinha a cada 2s, então o editor vê o resultado de uma geração sem precisar trocar de aba e voltar. Um arquivo binário ou ilegível como texto mostra um aviso no lugar do conteúdo, em vez de falhar.

## Aparência

Na topbar o usuário escolhe o modo (Light, Dark ou Pastel) e a cor de destaque (Índigo, Teal, Âmbar ou Violeta). A preferência fica salva por usuário e é aplicada ao portal inteiro sem flash. Todas as 12 combinações respeitam contraste WCAG AA; ao criar componentes novos, use os tokens de `portal/appaiforge/ui/theme.py` em vez de cores fixas.
