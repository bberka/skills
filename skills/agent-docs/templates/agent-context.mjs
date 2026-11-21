#!/usr/bin/env node
// Keeps the agent instructions from growing unnoticed. Agents load the root AGENTS.md in every session, a folder's
// AGENTS.md when they work in that folder, and a docs/agents page when its pointer matches the task, so every byte is
// paid for again and again. The budget file records the size of each group below. A pull request that adds
// instructions shows the growth in its diff, and CI rejects a group larger than the base branch's unless the pull
// request carries the `agent-context-increase` label (the workflow sets ALLOW_INCREASE=true).
//
//   node scripts/agent-context.mjs                fail unless the budget matches the files
//   node scripts/agent-context.mjs --write        rewrite the budget from the files
//   node scripts/agent-context.mjs --base <ref>   also fail when a group is larger than in <ref>'s budget
//
// No dependencies. Needs Node 18 or later and git.
import {execFileSync} from 'node:child_process';
import {existsSync, readFileSync, statSync, writeFileSync} from 'node:fs';
import process from 'node:process';
import {pathToFileURL} from 'node:url';

export const BUDGET = 'scripts/agent-context-budget.json';

// One budget key per group. A file counts in the first group with a matching pattern, so list the narrow group first.
// `*` matches inside one path segment, `**/` matches any number of folders, including none.
export const GROUPS = {
	'AGENTS.md': ['AGENTS.md', 'CLAUDE.md'],
	'**/AGENTS.md': ['**/AGENTS.md', '**/CLAUDE.md'],
	'docs/agents': ['docs/agents/**/*.md'],
};

// Text the repository does not own (installed skills, dependencies) and files a tool rewrites.
export const EXCLUDE = ['.claude/**', '.agents/**', '**/node_modules/**'];

export function globToRegExp(glob) {
	let source = '';
	for (let i = 0; i < glob.length; i++) {
		const char = glob[i];
		if (char === '*' && glob[i + 1] === '*') {
			if (glob[i + 2] === '/') {
				source += '(?:.*/)?';
				i += 2;
			} else {
				source += '.*';
				i += 1;
			}
		} else if (char === '*') source += '[^/]*';
		else if (char === '?') source += '[^/]';
		else source += char.replace(/[.+^${}()|[\]\\]/g, '\\$&');
	}
	return new RegExp(`^${source}$`);
}

// Tracked files plus untracked ones git does not ignore, so a new doc counts before it is staged and an ignored copy
// (a nested worktree, a build output) never does. A deleted file that is still in the index is skipped.
export function listFiles() {
	const out = execFileSync('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard'], {
		encoding: 'utf8',
		maxBuffer: 1 << 28,
	});
	return [...new Set(out.split('\0').filter(Boolean))].filter((file) => existsSync(file)).sort();
}

export function measure(files = listFiles(), groups = GROUPS, exclude = EXCLUDE) {
	const excluded = exclude.map(globToRegExp);
	const matchers = Object.entries(groups).map(([key, globs]) => [key, globs.map(globToRegExp)]);
	const sizes = Object.fromEntries(Object.keys(groups).map((key) => [key, 0]));
	for (const file of files) {
		if (excluded.some((pattern) => pattern.test(file))) continue;
		const group = matchers.find(([, patterns]) => patterns.some((pattern) => pattern.test(file)));
		if (group) sizes[group[0]] += statSync(file).size;
	}
	return sizes;
}

// A group is compared only when the base budget has it: a group added in this pull request has no base to grow from.
export function grown(current, base) {
	return Object.entries(current)
		.filter(([key, size]) => base[key] !== undefined && size > base[key])
		.map(([key, size]) => `${key}: ${base[key]} -> ${size} bytes (+${size - base[key]})`);
}

// The base has no budget file until the pull request that adds it merges.
function baseBudget(ref) {
	try {
		return JSON.parse(execFileSync('git', ['show', `${ref}:${BUDGET}`], {encoding: 'utf8', stdio: 'pipe'}));
	} catch {
		return undefined;
	}
}

function baseRefFrom(args) {
	const inline = args.find((arg) => arg.startsWith('--base='));
	if (inline) return inline.slice('--base='.length);
	const index = args.indexOf('--base');
	return index === -1 ? undefined : args[index + 1];
}

export function main(args) {
	process.chdir(execFileSync('git', ['rev-parse', '--show-toplevel'], {encoding: 'utf8'}).trim());
	const current = measure();
	if (args.includes('--write')) {
		writeFileSync(BUDGET, `${JSON.stringify(current, null, '\t')}\n`);
		console.log(`Wrote ${BUDGET}: ${JSON.stringify(current)}`);
		return 0;
	}

	const budget = existsSync(BUDGET) ? JSON.parse(readFileSync(BUDGET, 'utf8')) : undefined;
	if (JSON.stringify(budget) !== JSON.stringify(current)) {
		console.error(
			`${BUDGET} does not match the files.\nbudget:   ${JSON.stringify(budget)}\nmeasured: ${JSON.stringify(current)}\n` +
				'Run `node scripts/agent-context.mjs --write` and commit the result.',
		);
		return 1;
	}

	const baseRef = baseRefFrom(args);
	if (baseRef) {
		const base = baseBudget(baseRef);
		const growth = base === undefined ? [] : grown(current, base);
		if (growth.length > 0) {
			const report = `Agent instructions grew compared to ${baseRef}:\n${growth.join('\n')}`;
			if (process.env.ALLOW_INCREASE !== 'true') {
				console.error(`${report}\nCut the added text, or ask a maintainer for the agent-context-increase label.`);
				return 1;
			}
			console.log(`${report}\nAccepted by the agent-context-increase label.`);
		}
	}

	console.log(`Agent instructions: ${JSON.stringify(current)}`);
	return 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
	process.exitCode = main(process.argv.slice(2));
}
