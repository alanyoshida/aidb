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

## Repositório

Aba visível para quem gerencia o sistema. Liga o sistema a um projeto do GitLab para que as
mudanças passem por merge request, revisão e pipelines (preparação do projeto em
[Preparar um projeto no GitLab](gitlab.md)).

1. Copie a **chave pública** e cadastre-a no GitLab como chave de implantação com escrita.
2. Informe o **endereço SSH** (`git@gitlab.exemplo.com:time/app.git`), a **branch de trabalho**
   (padrão `homolog`), a **de destino** (padrão `main`) e, se o HTTP do GitLab não for
   `https://<host>`, o **endereço da API**. **Salvar**.
3. **Testar conexão**: confira a impressão digital do servidor e confirme. Se o servidor mudar de
   chave depois, nada é enviado até uma nova confirmação.
4. **Ativar vínculo**: o primeiro envio cria a branch de trabalho.

A partir daí:

- **Cada checkpoint** (execução, manual ou restauração) é enviado à branch de trabalho, com o editor
  como autor. Se o GitLab estiver fora do ar, o estado fica **envio pendente** e o envio sai no
  checkpoint seguinte ou em **Enviar agora**.
- **Antes de cada execução** o portal traz o que foi mergeado na branch de trabalho por outras
  pessoas (aparece em Checkpoints como "repositório remoto"). **Sincronizar agora** faz o mesmo sob
  demanda.
- **Alterações não salvas**: se o workspace tem alterações sem checkpoint e o GitLab tem novidades,
  a execução não começa e o chat explica. Na aba, escolha **Salvar como checkpoint** ou **Descartar**.
- **Divergente**: se o GitLab e o sistema alteraram os mesmos trechos, os envios param e a aba lista
  os arquivos. **Resolver no workspace** coloca as marcas de conflito nos arquivos para o agente
  resolver pelo chat — o próximo checkpoint sem marcas conclui; **Cancelar resolução** desfaz.
  **Adotar a versão do remoto** descarta o trabalho local não enviado (os checkpoints continuam
  restauráveis).
- **Solicitar promoção** abre o merge request da branch de trabalho para a de destino (ou mostra o
  que já está aberto) usando o **token de API**; sem token, mostra o link de criação.
- **Desativar vínculo** para envios e sincronizações sem mexer no workspace nem no GitLab.

## Sistema só implantação

Para o portal de produção, que só roda versões aprovadas. O sistema **só implantação** não tem
agente, chat nem checkpoints e não recebe credencial de LLM. Ele implanta tags de versão de um
repositório GitLab. Num portal de produção (`APPAIFORGE_INSTALLATION_ROLE=production`) é o único
tipo: a criação já vem com ele escolhido e sem provedor de LLM. Num portal de desenvolvimento,
escolha **Só implantação** em **Novo sistema**. O tipo não muda depois de criado.

A página do sistema tem as abas **Implantação**, Editor, Conexões, Domínios, Configurações e
Auditoria. Na aba **Implantação**:

1. Copie a **chave pública** e cadastre-a no GitLab como chave de implantação **sem escrita**
   ([Portal de produção](gitlab.md#7-portal-de-produção-sistema-só-implantação)).
2. Informe o **endereço SSH**, a **branch de destino** (padrão `main`) e o **padrão de tags**
   (padrão `v*`). **Salvar** e **Testar conexão**, conferindo a impressão digital do servidor.
3. **Versões** lista as tags do padrão da mais nova para a mais antiga (`v1.0.10` antes de
   `v1.0.2`), marcando a **atual** e as **já implantadas**. **Implantar** em qualquer linha:
   - a versão só é aceita se o commit da tag estiver na branch de destino;
   - as conexões que a versão exige (manifesto `.aidb/manifest.json`, gravado pela homologação a
     cada checkpoint) precisam estar cadastradas na aba Conexões com o mesmo nome. Faltando alguma,
     a implantação é recusada listando-as. Versão sem manifesto implanta com um aviso;
   - quando o `app/uv.lock` muda, as dependências são instaladas antes de o código trocar. Se a
     instalação falha, nada muda;
   - se a app da versão nova não responder em três checagens seguidas dentro do prazo, o portal
     volta à versão anterior e o histórico mostra **voltou à anterior** com o motivo.
4. **Voltar a uma versão anterior** é implantar a tag dela.
5. **Implantação automática**: ligada, implanta a tag mais nova do padrão desde que ela nunca tenha
   sido implantada neste sistema. Um rollback manual permanece até sair uma tag nova, e uma tag que
   falhou não é tentada de novo. A **detecção** é por **consulta periódica** ou por **webhook do
   GitLab**, com o endereço e o segredo mostrados na aba (**Trocar segredo** invalida o anterior).
6. **Histórico de implantações**: tag, commit, origem (manual, consulta periódica ou webhook),
   momento e resultado. Cada implantação também aparece na Auditoria.

## Aparência

Na topbar o usuário escolhe o modo (Light, Dark ou Pastel) e a cor de destaque (Índigo, Teal, Âmbar ou Violeta). A preferência fica salva por usuário e é aplicada ao portal inteiro sem flash. Todas as 12 combinações respeitam contraste WCAG AA; ao criar componentes novos, use os tokens de `portal/appaiforge/ui/theme.py` em vez de cores fixas.
