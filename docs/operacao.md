# Operação

← [README](../README.md)

- **Rollback**: página do sistema → Checkpoints → Restaurar.
- **Arquivar** (dono): para o container, preserva o workspace, remove a rota. **Excluir** (admin, só para arquivados): remove container + workspace.
- **Logs**: `docker compose logs -f portal` / `docker logs appaiforge-sys-<slug>`.
- **Saúde das conexões**: cada conexão é sondada periodicamente e exibe seu estado na página do sistema.
- **Auditoria**: toda ação de escrita da gestão (sistemas, conexões, usuários, provedores) fica numa trilha sem segredos, global para o admin e por sistema.
- **Estado da app**: o monitor marca `erro — app fora do ar` após 3 sondas falhas e recupera sozinho quando a app volta.
- **Reconciliação**: no boot e periodicamente o portal recria containers ausentes (workspace persiste no bind).
- **Backup**: volumes do Postgres do portal + diretório de workspaces (`APPAIFORGE_WORKSPACES_DIR`).
