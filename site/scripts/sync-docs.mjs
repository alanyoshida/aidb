// Gera as páginas de referência do site a partir de docs/, das ADRs, do README do chart e de
// seções do README. docs/ continua a fonte da verdade: as páginas geradas não são versionadas
// (ver site/.gitignore) e são refeitas a cada `npm run dev` ou `npm run build`.
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync, existsSync, statSync } from 'node:fs';
import { dirname, join, posix, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import GithubSlugger from 'github-slugger';

const SITE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const REPO = resolve(SITE, '..');
const OUT = join(SITE, 'src/content/docs');
const GENERATED_DIRS = ['referencia', 'decisoes', 'identidade', 'operacao-e-observabilidade'];
const BASE = (process.env.SITE_BASE ?? '/aidb').replace(/\/$/, '');
const GITHUB = 'https://github.com/alanyoshida/aidb';

// Páginas inteiras: arquivo do repositório -> rota no site.
const PAGES = [
	{ src: 'docs/guia-de-uso.md', slug: 'referencia/guia-de-uso', title: 'Guia de uso' },
	{ src: 'docs/configuracao.md', slug: 'referencia/variaveis-de-ambiente', title: 'Variáveis de ambiente' },
	{ src: 'docs/operacao.md', slug: 'referencia/operacao', title: 'Instalar e operar em produção' },
	{ src: 'docs/driver-kubernetes.md', slug: 'referencia/kubernetes', title: 'Driver Kubernetes' },
	{ src: 'deploy/helm/appaiforge-portal/README.md', slug: 'referencia/chart-helm', title: 'Chart Helm do portal' },
	{ src: 'docs/llm-e-broker.md', slug: 'referencia/llm-e-broker', title: 'Chave de LLM e broker de inferência' },
	{ src: 'docs/gitlab.md', slug: 'referencia/gitlab', title: 'Repositório no GitLab' },
	{ src: 'docs/autenticacao.md', slug: 'identidade/autenticacao', title: 'Autenticação em detalhe' },
	{ src: 'docs/seguranca.md', slug: 'referencia/seguranca', title: 'Gate de SQL e confinamento em detalhe' },
	{ src: 'docs/roadmap-confinamento-do-agente.md', slug: 'referencia/roadmap-confinamento', title: 'Roadmap de confinamento do agente' },
	{ src: 'docs/testes.md', slug: 'referencia/testes', title: 'Testes' },
	{ src: 'docs/adr/README.md', slug: 'decisoes', title: 'Decisões de arquitetura' },
];

// Seções do README que viram páginas próprias.
const README_SECTIONS = [
	{ heading: 'Arquitetura', slug: 'comecar/arquitetura', title: 'Arquitetura', description: 'Como o portal, o container de cada sistema, o gate de SQL e o broker se ligam.' },
	{ heading: 'Usuários e papéis', slug: 'identidade/usuarios-e-papeis', title: 'Usuários e papéis', description: 'Tipos de usuário, a capacidade de DB Manager e o acesso aos sistemas.' },
	{ heading: 'Login e SSO', slug: 'identidade/login-e-sso', title: 'Login e SSO', description: 'Modo local ou OIDC, e como as apps recebem a identidade do usuário.' },
	{ heading: 'Observabilidade', slug: 'operacao-e-observabilidade/observabilidade', title: 'Observabilidade', description: 'Traços, métricas e logs por OpenTelemetry, com Elastic ou Grafana.' },
];

const ADR_DIR = 'docs/adr';

function read(path) {
	return readFileSync(join(REPO, path), 'utf8');
}

function splitTitle(md) {
	const lines = md.split('\n');
	const i = lines.findIndex((l) => /^# /.test(l));
	if (i === -1) return { h1: null, body: md };
	const h1 = lines[i].replace(/^# /, '').trim();
	lines.splice(i, 1);
	return { h1, body: lines.join('\n') };
}

function stripNavLines(body) {
	// Linhas de navegação do repositório ("← [README](../README.md) · ...") não fazem sentido no site.
	return body.replace(/^← .*\n+/m, '');
}

function readmeSection(readme, heading) {
	const lines = readme.split('\n');
	const start = lines.findIndex((l) => l === `## ${heading}`);
	if (start === -1) throw new Error(`Seção "${heading}" não encontrada no README`);
	let end = lines.length;
	let inFence = false;
	for (let i = start + 1; i < lines.length; i++) {
		if (/^```/.test(lines[i])) inFence = !inFence;
		if (!inFence && /^## /.test(lines[i])) {
			end = i;
			break;
		}
	}
	// Desce um nível os títulos internos: ### vira ##.
	let fence = false;
	return lines
		.slice(start + 1, end)
		.map((l) => {
			if (/^```/.test(l)) fence = !fence;
			return !fence && /^###+ /.test(l) ? l.slice(1) : l;
		})
		.join('\n')
		.trim();
}

function headingSlugs(md) {
	const slugger = new GithubSlugger();
	const slugs = new Set();
	let fence = false;
	for (const l of md.split('\n')) {
		if (/^```/.test(l)) fence = !fence;
		const m = !fence && l.match(/^#{1,6} (.+)$/);
		if (m) slugs.add(slugger.slug(m[1].replace(/`/g, '')));
	}
	return slugs;
}

// Mapa arquivo do repositório -> rota, e âncora do README -> rota.
const routeOf = new Map(PAGES.map((p) => [p.src, p.slug]));
for (const f of readdirSync(join(REPO, ADR_DIR))) {
	if (/^\d{4}-.+\.md$/.test(f)) routeOf.set(`${ADR_DIR}/${f}`, `decisoes/${f.replace(/\.md$/, '')}`);
}
const readme = read('README.md');
const readmeAnchor = new Map();
for (const s of README_SECTIONS) {
	const slugger = new GithubSlugger();
	readmeAnchor.set(slugger.slug(s.heading), { slug: s.slug, anchor: '' });
	for (const a of headingSlugs(readmeSection(readme, s.heading))) readmeAnchor.set(a, { slug: s.slug, anchor: a });
}
// Seções do README que o site cobre com páginas escritas à mão.
readmeAnchor.set('segurança', { slug: 'seguranca', anchor: '' });
readmeAnchor.set('instalação', { slug: 'comecar/instalacao', anchor: '' });

const url = (slug, anchor) => `${BASE}/${slug}/${anchor ? `#${anchor}` : ''}`;

function rewriteLinks(md, srcPath) {
	const srcDir = posix.dirname(srcPath);
	let fence = false;
	return md
		.split('\n')
		.map((line) => {
			if (/^```/.test(line)) fence = !fence;
			if (fence) return line;
			return line.replace(/\]\(([^)\s]+)\)/g, (whole, target) => {
				if (/^(https?:|mailto:)/.test(target)) return whole;
				const [pathPart, anchor = ''] = target.split('#');
				if (!pathPart) {
					// Âncora na mesma página; no README, aponta para a página que ficou com a seção.
					if (srcPath === 'README.md' && readmeAnchor.has(anchor)) {
						const r = readmeAnchor.get(anchor);
						return `](${url(r.slug, r.anchor)})`;
					}
					return whole;
				}
				const repoPath = posix.normalize(posix.join(srcDir, pathPart)).replace(/\/$/, '');
				if (repoPath === 'README.md') {
					const r = readmeAnchor.get(anchor);
					return `](${r ? url(r.slug, r.anchor) : `${GITHUB}#${anchor}`})`;
				}
				if (routeOf.has(repoPath)) return `](${url(routeOf.get(repoPath), anchor)})`;
				const abs = join(REPO, repoPath);
				const kind = existsSync(abs) && statSync(abs).isDirectory() ? 'tree' : 'blob';
				return `](${GITHUB}/${kind}/main/${repoPath}${anchor ? `#${anchor}` : ''})`;
			});
		})
		.join('\n');
}

function frontmatter({ title, description, editPath, sidebar }) {
	const lines = ['---', `title: ${JSON.stringify(title)}`];
	if (description) lines.push(`description: ${JSON.stringify(description)}`);
	lines.push(editPath ? `editUrl: ${JSON.stringify(`${GITHUB}/edit/main/${editPath}`)}` : 'editUrl: false');
	if (sidebar) lines.push('sidebar:', ...Object.entries(sidebar).map(([k, v]) => `  ${k}: ${JSON.stringify(v)}`));
	lines.push('---', '');
	return lines.join('\n');
}

function firstParagraph(body) {
	const p = body
		.split(/\n\s*\n/)
		.map((b) => b.trim())
		.find((b) => b && !/^[#>|`*-]|^\d+\.|^</.test(b));
	if (!p) return undefined;
	const text = p.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[*`_]/g, '').replace(/\s+/g, ' ');
	return text.length > 180 ? `${text.slice(0, 177).replace(/\s\S*$/, '')}…` : text;
}

function write(slug, content) {
	const file = join(OUT, `${slug}${slug.split('/').length === 1 ? '/index' : ''}.md`);
	mkdirSync(dirname(file), { recursive: true });
	writeFileSync(file, content);
	return relative(SITE, file);
}

for (const dir of GENERATED_DIRS) rmSync(join(OUT, dir), { recursive: true, force: true });

const written = [];
for (const p of PAGES) {
	const { body } = splitTitle(read(p.src));
	const clean = stripNavLines(body).trim();
	written.push(
		write(p.slug, frontmatter({ title: p.title, description: firstParagraph(clean), editPath: p.src }) + rewriteLinks(clean, p.src) + '\n'),
	);
}

for (const f of readdirSync(join(REPO, ADR_DIR)).sort()) {
	if (!/^\d{4}-.+\.md$/.test(f)) continue;
	const src = `${ADR_DIR}/${f}`;
	const { h1, body } = splitTitle(read(src));
	const [num, ...rest] = h1.split(' — ');
	const title = rest.length ? `${num} · ${rest.join(' — ')}` : h1;
	written.push(
		write(
			routeOf.get(src),
			frontmatter({ title, description: firstParagraph(body.replace(/^\*.*$/gm, '')), editPath: src, sidebar: { label: `${num} ${rest.join(' — ').split(';')[0]}` } }) +
				rewriteLinks(body.trim(), src) +
				'\n',
		),
	);
}

for (const s of README_SECTIONS) {
	written.push(write(s.slug, frontmatter({ title: s.title, description: s.description, editPath: 'README.md' }) + rewriteLinks(readmeSection(readme, s.heading), 'README.md') + '\n'));
}

// Versão do produto para as páginas escritas à mão: lida do pyproject, nunca digitada.
const version = read('portal/pyproject.toml').match(/^version = "([^"]+)"/m)[1];
mkdirSync(join(SITE, 'src/generated'), { recursive: true });
writeFileSync(join(SITE, 'src/generated/version.json'), JSON.stringify({ version }) + '\n');

console.log(`sync-docs: ${written.length} páginas geradas, versão ${version}`);
