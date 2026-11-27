// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import mermaid from 'astro-mermaid';

// GitHub Pages do repositório: https://alanyoshida.github.io/aidb/
const base = process.env.SITE_BASE ?? '/aidb';

export default defineConfig({
	site: 'https://alanyoshida.github.io',
	base,
	trailingSlash: 'always',
	integrations: [
		// Precisa vir antes do Starlight para processar os blocos ```mermaid.
		mermaid({
			theme: 'neutral',
			autoTheme: true,
			enableLog: false,
			mermaidConfig: { themeVariables: { fontSize: '15px' }, flowchart: { nodeSpacing: 36, rankSpacing: 44 } },
		}),
		starlight({
			title: 'AIDB',
			description:
				'Apps administrativas geradas por um agente de IA sobre o seu banco de dados, com o agente confinado pelo kernel e cada SQL classificada antes de chegar ao banco.',
			defaultLocale: 'root',
			locales: { root: { label: 'Português', lang: 'pt-BR' } },
			logo: { src: './src/assets/logo.svg', replacesTitle: false },
			favicon: '/favicon.svg',
			social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/alanyoshida/aidb' }],
			customCss: ['@fontsource-variable/geist', '@fontsource-variable/geist-mono', './src/styles/theme.css'],
			components: { Hero: './src/components/Hero.astro' },
			lastUpdated: false,
			tableOfContents: { minHeadingLevel: 2, maxHeadingLevel: 3 },
			sidebar: [
				{
					label: 'Começar',
					items: [
						{ label: 'Visão geral', slug: 'comecar/visao-geral' },
						{ label: 'Arquitetura', slug: 'comecar/arquitetura' },
						{ label: 'Instalação', slug: 'comecar/instalacao' },
						{ label: 'Guia de uso', slug: 'referencia/guia-de-uso' },
					],
				},
				{
					label: 'Instalação e configuração',
					items: [
						{ label: 'Produção: Docker e Helm', slug: 'referencia/operacao' },
						{ label: 'Variáveis de ambiente', slug: 'referencia/variaveis-de-ambiente' },
						{ label: 'Driver Kubernetes', slug: 'referencia/kubernetes' },
						{ label: 'Chart Helm', slug: 'referencia/chart-helm' },
						{ label: 'LLM e broker de inferência', slug: 'referencia/llm-e-broker' },
						{ label: 'Repositório no GitLab', slug: 'referencia/gitlab' },
					],
				},
				{
					label: 'Usuários e SSO',
					items: [
						{ label: 'Usuários e papéis', slug: 'identidade/usuarios-e-papeis' },
						{ label: 'Login e SSO', slug: 'identidade/login-e-sso' },
						{ label: 'Autenticação em detalhe', slug: 'identidade/autenticacao' },
					],
				},
				{
					label: 'Segurança',
					items: [
						{ label: 'Como a segurança funciona', slug: 'seguranca' },
						{ label: 'Gate de SQL e confinamento', slug: 'referencia/seguranca' },
						{ label: 'Roadmap de confinamento', slug: 'referencia/roadmap-confinamento' },
					],
				},
				{
					label: 'Operação',
					items: [
						{ label: 'Observabilidade', slug: 'operacao-e-observabilidade/observabilidade' },
						{ label: 'Testes', slug: 'referencia/testes' },
					],
				},
				{
					label: 'Decisões (ADRs)',
					collapsed: true,
					items: [{ autogenerate: { directory: 'decisoes' } }],
				},
			],
		}),
	],
});
