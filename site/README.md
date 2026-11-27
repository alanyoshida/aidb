# Site do AIDB

Site de apresentação e documentação, publicado em https://alanyoshida.github.io/aidb/ pelo
workflow [`.github/workflows/site.yml`](../.github/workflows/site.yml) a cada push na `main` que
mexa no site, em `docs/`, no README ou no README do chart.

Feito com [Astro Starlight](https://starlight.astro.build).

## Rodar localmente

```bash
cd site
npm install
npm run dev        # http://localhost:4321/aidb/
npm run build      # gera dist/
```

## De onde vem cada página

- **Escritas à mão** (`src/content/docs/`): visão geral, instalação e a área de segurança. A página
  inicial é `src/pages/index.astro`, com o hero em `src/components/Hero.astro`.
- **Geradas** por `scripts/sync-docs.mjs` a cada `dev` e `build`, e fora do git: a referência
  (`docs/*.md`), as ADRs (`docs/adr/`), o README do chart e as seções Arquitetura, Usuários e papéis,
  Login e SSO e Observabilidade do README. Para mudar essas páginas, edite a fonte em `docs/` ou no
  README; o script reescreve os links entre documentos para as rotas do site.
- **Versão do produto**: lida de `portal/pyproject.toml` no build, nunca escrita à mão.

## Screenshots

As imagens em `src/assets/screens/` são capturas reais do portal rodando localmente, com uma
usuária e um banco de demonstração (dados fictícios). Cada arquivo traz a origem embutida nos
metadados. Ao trocar uma captura, mantenha a largura de 1920 px; o build gera as versões menores.
