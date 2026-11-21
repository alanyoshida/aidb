# Operação

← [README](../README.md)

- **Rollback**: página do sistema → Checkpoints → Restaurar. Em sistema só implantação: aba Implantação → **Implantar** na tag anterior.
- **Portal de produção**: instalação própria (banco, volumes e Traefik) com `APPAIFORGE_INSTALLATION_ROLE=production`; recusa criar e provisionar sistema com agente, e um sistema com agente encontrado na reconciliação fica em erro com o motivo. Rode `alembic upgrade head` antes de subir uma versão nova do portal.
- **Implantação interrompida**: se o portal reinicia no meio de uma implantação, ela fica como falha ("interrompida") na subida seguinte e o workspace volta ao commit da última implantação com sucesso.
- **Arquivar** (dono): para o container, preserva o workspace, remove a rota. **Excluir** (admin, só para arquivados): remove container + workspace.
- **Logs**: `docker compose logs -f portal` / `docker logs appaiforge-sys-<slug>`.
- **Saúde das conexões**: cada conexão é sondada periodicamente e exibe seu estado na página do sistema.
- **Auditoria**: toda ação de escrita da gestão (sistemas, conexões, usuários, provedores) fica numa trilha sem segredos, global para o admin e por sistema.
- **Estado da app**: o monitor marca `erro — app fora do ar` após 3 sondas falhas e recupera sozinho quando a app volta.
- **Reconciliação**: no boot e periodicamente o portal recria containers ausentes (workspace persiste no bind).
- **Backup**: volumes do Postgres do portal + diretório de workspaces (`APPAIFORGE_WORKSPACES_DIR`).
