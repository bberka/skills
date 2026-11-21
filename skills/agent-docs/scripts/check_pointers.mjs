#!/usr/bin/env node
// Checks that a repository's agent instructions point at things that exist.
//
//   node check_pointers.mjs [--repo <dir>] [--docs <folder>] [--root-lines 60] [--root-bytes 5000] [--folder-lines 15]
//
// Reads every AGENTS.md and CLAUDE.md git knows about (tracked or untracked, not ignored, skipping .claude/, .agents/,
// node_modules/) and every Markdown file in the docs folder (default: docs/agents).
//
// Errors (exit 1): a Markdown link or an @import whose file or #heading does not exist.
// Warnings: a `run <script>` with no such script in any package.json, a backticked path that matches no file or
// folder git knows (shorthand like `src/shared` passes when some path ends with it), a doc the root AGENTS.md does not
// point to, a size over its cap, an AGENTS.md without a CLAUDE.md that imports it, a CLAUDE.md that holds more than
// imports.
// Notes: backticked paths .gitignore matches (build output, local state). They are listed apart and not checked, so the
// result is the same before and after a build.
// No dependencies. Needs Node 18 or later and git.
import {execFileSync} from 'node:child_process';
import {existsSync, readFileSync, statSync} from 'node:fs';
import {dirname, join, normalize, relative} from 'node:path';
import process from 'node:process';

const args = process.argv.slice(2);
const option = (name, fallback) => {
	const index = args.indexOf(name);
	return index === -1 ? fallback : args[index + 1];
};
if (args.includes('--help') || args.includes('-h')) {
	const lines = readFileSync(new URL(import.meta.url), 'utf8').split('\n').slice(1);
	const header = lines.slice(0, lines.findIndex((line) => !line.startsWith('//')));
	console.log(header.join('\n').replace(/^\/\/ ?/gm, ''));
	process.exit(0);
}
const repo = execFileSync('git', ['-C', option('--repo', '.'), 'rev-parse', '--show-toplevel'], {encoding: 'utf8'}).trim();
const docsFolder = option('--docs', 'docs/agents').replace(/\/$/, '');
const caps = {
	rootLines: Number(option('--root-lines', 60)),
	rootBytes: Number(option('--root-bytes', 5000)),
	folderLines: Number(option('--folder-lines', 15)),
};

const SKIP = [/^\.claude\//, /^\.agents\//, /(^|\/)node_modules\//];
const listed = execFileSync('git', ['-C', repo, 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], {
	encoding: 'utf8',
	maxBuffer: 1 << 28,
})
	.split('\0')
	.filter((file) => file && existsSync(join(repo, file)));
const all = listed.filter((file) => !SKIP.some((rule) => rule.test(file)));
const rulesFiles = all.filter((file) => /(^|\/)(AGENTS|CLAUDE)\.md$/.test(file));
const docs = all.filter((file) => file.startsWith(`${docsFolder}/`) && file.endsWith('.md'));
const files = [...new Set([...rulesFiles, ...docs])].sort();

const errors = [];
const warnings = [];
const notes = [];
const unmatched = [];
const read = (file) => readFileSync(join(repo, file), 'utf8');

// GitHub's heading anchors: lowercase, punctuation dropped, spaces to hyphens, repeats numbered.
const anchorCache = new Map();
function anchors(file) {
	if (anchorCache.has(file)) return anchorCache.get(file);
	const seen = new Map();
	const result = new Set();
	for (const line of stripCode(read(file)).split('\n')) {
		const match = /^#{1,6}\s+(.*?)\s*#*\s*$/.exec(line);
		if (!match) continue;
		const base = match[1]
			.replace(/<[^>]+>/g, '')
			.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
			.replace(/[`*_~]/g, '')
			.toLowerCase()
			.replace(/[^\p{L}\p{N}\s-]/gu, '')
			.replace(/\s/g, '-');
		const count = seen.get(base) ?? 0;
		seen.set(base, count + 1);
		result.add(count === 0 ? base : `${base}-${count}`);
	}
	for (const match of read(file).matchAll(/<a\s+(?:name|id)="([^"]+)"/g)) result.add(match[1]);
	anchorCache.set(file, result);
	return result;
}

// Blank out fenced blocks so their contents are neither links nor headings; keep line numbers.
function stripCode(text) {
	let fenced = false;
	return text
		.split('\n')
		.map((line) => {
			if (/^\s*(```|~~~)/.test(line)) {
				fenced = !fenced;
				return '';
			}
			return fenced ? '' : line;
		})
		.join('\n');
}

function resolveTarget(from, target) {
	const path = target.startsWith('/') ? target.slice(1) : join(dirname(from), target);
	return normalize(path);
}

function checkLink(file, line, target) {
	if (/^[a-z][a-z0-9+.-]*:/i.test(target) || target.startsWith('//')) return;
	const [rawPath, anchor] = target.split('#');
	const path = decodeURI(rawPath);
	const resolved = path === '' ? file : resolveTarget(file, path);
	if (relative(repo, join(repo, resolved)).startsWith('..')) return;
	if (!existsSync(join(repo, resolved))) {
		errors.push(`${file}:${line}: link to ${target}: ${resolved} does not exist`);
		return;
	}
	if (anchor && resolved.endsWith('.md') && statSync(join(repo, resolved)).isFile()) {
		if (!anchors(resolved).has(anchor.toLowerCase())) {
			errors.push(`${file}:${line}: link to ${target}: no heading #${anchor} in ${resolved}`);
		}
	}
}

const scripts = new Set();
for (const manifest of all.filter((file) => /(^|\/)package\.json$/.test(file))) {
	try {
		for (const name of Object.keys(JSON.parse(read(manifest)).scripts ?? {})) scripts.add(name);
	} catch {
		warnings.push(`${manifest}: not valid JSON, its scripts were not read`);
	}
}

// Every tracked path and its folders, so a shorthand like `src/shared` or `platform.ts` resolves when some file ends with it.
const known = new Set();
for (const file of listed) {
	const parts = file.split('/');
	for (let i = 1; i <= parts.length; i++) known.add(parts.slice(0, i).join('/'));
}

const rootLinks = new Set();
for (const file of files) {
	const text = stripCode(read(file));
	const lines = text.split('\n');
	lines.forEach((content, index) => {
		const line = index + 1;
		const prose = content.replace(/`[^`]*`/g, (span) => ' '.repeat(span.length));
		for (const match of prose.matchAll(/!?\[[^\]]*\]\(\s*<?((?:[^()\s>]|\([^()\s]*\))+)>?(?:\s+"[^"]*")?\s*\)/g)) {
			checkLink(file, line, match[1]);
			if (file === 'AGENTS.md') rootLinks.add(resolveTarget(file, match[1].split('#')[0]));
		}
		const reference = /^\s*\[[^\]]+\]:\s*<?(\S+?)>?(\s|$)/.exec(prose);
		if (reference) checkLink(file, line, reference[1]);
		const importLine = /^\s*@(\S+)\s*$/.exec(content);
		if (importLine && !importLine[1].startsWith('~')) {
			const target = resolveTarget(file, importLine[1]);
			if (!existsSync(join(repo, target))) errors.push(`${file}:${line}: @${importLine[1]}: ${target} does not exist`);
		}
		for (const span of content.matchAll(/`([^`]+)`/g)) checkSpan(file, line, span[1]);
	});
}

function checkSpan(file, line, span) {
	for (const match of span.matchAll(/\b(?:pnpm|npm|yarn|bun|vp)\s+(?:--?\S+\s+(?:\S+\s+)?)*run\s+([\w:.@/-]+)/g)) {
		if (!scripts.has(match[1])) warnings.push(`${file}:${line}: \`${span}\`: no script "${match[1]}" in any package.json`);
	}
	const token = span.trim();
	if (/[<>{}$*?|\s]/.test(token) || !/^[\w.@-]+(\/[\w.@-]+)*\/?$/.test(token)) return;
	const looksLikePath = token.includes('/') || /\.(md|mjs|cjs|js|ts|tsx|jsx|json|ya?ml|toml|py|sh|css)$/.test(token);
	if (!looksLikePath || /^\d/.test(token)) return;
	if (/^(@|origin\/|https?:)/.test(token) || /^\.[^/]*$/.test(token)) return;
	const bare = token.replace(/\/$/, '');
	const beside = resolveTarget(file, bare);
	if (known.has(beside) || known.has(bare) || [...known].some((path) => path.endsWith(`/${bare}`))) return;
	unmatched.push({file, line, token, paths: [beside, bare]});
}

// Paths .gitignore matches exist only after a build or a local run, so they are notes, not warnings.
function sortIgnored() {
	if (unmatched.length === 0) return;
	const queries = [...new Set(unmatched.flatMap(({paths}) => paths.flatMap((path) => [path, `${path}/`])))];
	let ignored = new Set();
	try {
		ignored = new Set(execFileSync('git', ['-C', repo, 'check-ignore', '--no-index', '--stdin'], {encoding: 'utf8', input: queries.join('\n')}).split('\n'));
	} catch (error) {
		ignored = new Set(String(error.stdout ?? '').split('\n'));
	}
	for (const {file, line, token, paths} of unmatched) {
		if (paths.some((path) => ignored.has(path) || ignored.has(`${path}/`))) notes.push(`${file}:${line}: \`${token}\` is gitignored, not checked`);
		else warnings.push(`${file}:${line}: \`${token}\` matches no file or folder git knows`);
	}
}

sortIgnored();
for (const doc of docs) {
	if (!rootLinks.has(doc)) warnings.push(`${doc}: the root AGENTS.md does not point to it`);
}

// A repository worked in Claude Code has a root CLAUDE.md; only then does each AGENTS.md need one beside it.
const usesClaude = rulesFiles.includes('CLAUDE.md');
const sizeOf = (file) => ({lines: read(file).trimEnd().split('\n').length, bytes: statSync(join(repo, file)).size});
for (const file of rulesFiles.filter((name) => name.endsWith('AGENTS.md'))) {
	const {lines, bytes} = sizeOf(file);
	if (file === 'AGENTS.md') {
		if (lines > caps.rootLines || bytes > caps.rootBytes) {
			warnings.push(`AGENTS.md: ${lines} lines, ${bytes} bytes (cap about ${caps.rootLines} lines, ${caps.rootBytes} bytes)`);
		}
	} else if (lines > caps.folderLines) {
		warnings.push(`${file}: ${lines} lines (cap about ${caps.folderLines})`);
	}
	const claude = join(dirname(file), 'CLAUDE.md');
	if (usesClaude && (!existsSync(join(repo, claude)) || !/^\s*@AGENTS\.md\s*$/m.test(read(claude)))) {
		warnings.push(`${file}: no CLAUDE.md beside it that imports it (@AGENTS.md), so Claude Code does not load it`);
	}
}
for (const file of rulesFiles.filter((name) => name.endsWith('CLAUDE.md'))) {
	const extra = read(file)
		.split('\n')
		.filter((line) => line.trim() && !/^\s*@\S+\s*$/.test(line) && !/^#{1,6}\s/.test(line));
	if (extra.length > 0) warnings.push(`${file}: ${extra.length} lines besides imports and headings; they load on top of AGENTS.md`);
}

console.log(`Checked ${files.length} files: ${rulesFiles.length} AGENTS.md/CLAUDE.md, ${docs.length} in ${docsFolder}/.`);
if (existsSync(join(repo, 'AGENTS.md'))) {
	const {lines, bytes} = sizeOf('AGENTS.md');
	console.log(`Root AGENTS.md: ${lines} lines, ${bytes} bytes.`);
}
for (const message of errors) console.log(`error: ${message}`);
for (const message of warnings) console.log(`warning: ${message}`);
for (const message of notes) console.log(`note: ${message}`);
console.log(`${errors.length} errors, ${warnings.length} warnings, ${notes.length} gitignored paths not checked.`);
process.exitCode = errors.length > 0 ? 1 : 0;
