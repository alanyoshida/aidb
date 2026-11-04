# Tasks

> O código destes itens já existe na árvore de trabalho; o apply deve verificar
> cada um contra o comportamento descrito nos specs antes de marcá-lo.

## 1. Fundação do tema

- [x] 1.1 Definir em `portal/appaiforge/ui/theme.py` os tokens de cor das 3 modalidades × 4 cores de destaque, incluindo os pares "on-" para texto sobre preenchimento. Verificar: uma função que gere os tokens de uma combinação retorna o conjunto completo para as 12 combinações, sem chave faltando.

- [x] 1.2 Derivar as variáveis de marca do Quasar (`--q-primary`, `--q-positive`, `--q-negative`, `--q-warning`, `--q-info`) dos tokens, e registrar as cores próprias usadas em estados neutros. Verificar: inspecionar `getComputedStyle(document.documentElement)` no navegador e confirmar que as variáveis refletem o tema ativo.

- [x] 1.3 Escrever a folha de estilo do portal lendo apenas os tokens, cobrindo fundo de página, superfícies, cabeçalho, abas, campos de formulário, tabelas e separadores. Verificar: trocar de modo no portal altera todas essas áreas sem deixar nenhuma com a cor anterior.

## 2. Preferência por usuário

- [x] 2.1 Adicionar o campo de preferência de tema ao modelo de usuário em `portal/appaiforge/models.py`, com valor padrão. Verificar: `python -m py_compile` passa e o campo aparece no modelo.

- [x] 2.2 Criar a migration correspondente em `portal/migrations/versions/`, encadeada no head atual. Verificar: `alembic upgrade head` aplica sem erro e `alembic heads` retorna um único head.

- [x] 2.3 Emitir o CSS do tema do usuário no `<head>` a partir de `render_header`, em `portal/appaiforge/ui/common.py`. Verificar: abrir uma página autenticada e confirmar que o conteúdo já aparece no tema escolhido, sem exibir outro antes.

- [x] 2.4 Adicionar o seletor de modo e cor à barra superior, gravando a escolha no perfil e recarregando a página. Verificar: escolher um tema, sair e entrar de novo, e confirmar que ele foi mantido.

## 3. Aparência do chat

- [x] 3.1 Derivar as cores das bolhas, avatares e campo de entrada do chat dos tokens do tema, em `theme.py` e `portal/appaiforge/ui/chat.py`. Verificar: em cada modo, as bolhas do agente e do usuário seguem o tema.

- [x] 3.2 Registrar o instante de criação nos eventos de execução em memória, em `portal/appaiforge/harness/base.py`, espelhando o campo já existente no registro persistido. Verificar: a suíte unitária do harness continua passando.

- [x] 3.3 Exibir data e hora ao lado do nome do remetente, convertendo de UTC para o fuso configurado em `portal/appaiforge/config.py`. Verificar: abrir uma sessão com histórico e conferir que cada mensagem mostra o horário do envio.

- [x] 3.4 Exibir o indicador de disponibilidade do agente junto da descrição do estado, com animação apenas quando ocupado e sem movimento sob preferência de animação reduzida. Verificar: enviar um pedido e amostrar o estado do indicador durante a execução, confirmando a transição livre → ocupado → livre.

- [x] 3.5 Substituir os identificadores internos dos eventos de transição por rótulos em português. Verificar: executar um pedido e confirmar que os marcadores aparecem em português no chat.

## 4. Correções de comportamento silencioso

- [x] 4.1 Informar o provedor e o modelo do sistema ao harness no envio do prompt, em `portal/appaiforge/harness/opencode.py`. Verificar: enviar um pedido em um sistema configurado e confirmar que a resposta do agente aparece no chat.

- [x] 4.2 Dar retorno à criação manual de checkpoint em `portal/appaiforge/ui/system_detail.py`, distinguindo checkpoint criado de nada a salvar. Verificar: acionar o botão com o workspace limpo e depois com uma alteração, conferindo as duas mensagens.

- [x] 4.3 Incluir o motivo relatado pelo driver na falha do teste de conexão, removendo a senha do texto, em `portal/appaiforge/services/connections.py`. Verificar: tentar uma conexão com host inalcançável e outra com senha errada, conferindo que a mensagem traz o motivo e não contém a senha.

## 5. Verificação de contraste

- [x] 5.1 Verificar por cálculo que todos os pares de texto e fundo das 12 combinações atingem 4.5:1. Verificar: rodar o cálculo sobre os tokens e confirmar zero reprovações.

- [x] 5.2 Varrer a interface renderizada calculando o fundo efetivo de cada texto visível, nas páginas de lista, detalhe do sistema e administração, em pelo menos os modos claro e escuro. Verificar: zero falhas em cada varredura, com a contagem de elementos checados registrada.

- [x] 5.3 Confirmar que notificações, cartões de erro e o aviso de conexão perdida seguem o tema. Verificar: disparar cada um deles e medir o contraste do texto contra o próprio fundo.

## 6. Regressão

- [x] 6.1 Rodar a suíte unitária do portal. Verificar: `pytest tests/unit/` passa inteira.
