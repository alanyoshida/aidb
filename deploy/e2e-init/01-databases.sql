-- Bancos auxiliares para os testes E2E (executado apenas na inicialização do volume)
CREATE DATABASE appaiforge2;
-- Banco próprio do LiteLLM (backend do broker de inferência); a migração
-- Prisma dele cria as tabelas, mas não o database.
CREATE DATABASE litellm;
