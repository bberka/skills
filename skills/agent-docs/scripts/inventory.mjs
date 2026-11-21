#!/usr/bin/env node
// Builds and checks the rule inventory: one row per rule in the agent instruction files, each given one destination.
//
//   node inventory.mjs [--repo <dir>] [--out <file>] [extra.md ...]   write the skeleton (default: stdout)
//   node inventory.mjs --check <file> [--repo <dir>]                  fail on a row without a valid destination
//
// The skeleton covers every AGENTS.md and CLAUDE.md git knows about (skipping .claude/, .agents/, node_modules/), plus
// any extra files named, such as a doc you will split. A unit is a list item, a table row, a paragraph, or a fenced
// block, with the heading it sits under. Split a unit that holds several rules into rows 12a, 12b, and so on.
// Every other Markdown file those files link to gets one row for the whole doc.
//
// Destinations: `root`, `doc <path>`, `folder <path>` (the per-folder AGENTS.md), `delete`. A `delete` row needs a
// reason: what enforces it (file, script, hook, CI job), why it is stale, or where it already lives. With --repo,
// --check also fails when a doc or folder destination does not exist yet, so run it that way after writing the files.
// No dependencies. Needs Node 18 or later and git.
import {execFileSync} from 'node:child_process';
import {existsSync, readFileSync, statSync, writeFileSync} from 'node:fs';
import {dirname, join, normalize} from 'node:path';
import process from 'node:process';

const args = process.argv.slice(2);
const option = (name) => {
	const index = args.indexOf(name);
	return index === -1 ? undefined : args[index + 1];
};
if (args.includes('--help') || args.includes('-h')) {
	console.log(readFileSync(new URL(import.meta.url), 'utf8').split('\n').slice(1, 15).join('\n').replace(/^\/\/ ?/gm, ''));
	process.exit(0);
}
const repoArg = option('--repo');
const repo = execFileSync('git', ['-C', repoArg ?? '.', 'rev-parse', '--show-toplevel'], {encoding: 'utf8'}).trim();

const checkFile = option('--check');
process.exitCode = checkFile ? check(checkFile) : write();

function sources() {
	const valued = new Set(['--repo', '--out']);
	const extra = args.filter((arg, index) => !arg.startsWith('--') && !valued.has(args[index - 1]));
	const listed = execFileSync('git', ['-C', repo, 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], {
		encoding: 'utf8',
		maxBuffer: 1 << 28,
	})
		.split('\0')
		.filter((file) => /(^|\/)(AGENTS|CLAUDE)\.md$/.test(file))
		.filter((file) => !/^\.claude\/|^\.agents\/|(^|\/)node_modules\//.test(file))
		.filter((file) => existsSync(join(repo, file)));
	const rootFirst = (a, b) => (a.split('/').length - b.split('/').length) || a.localeCompare(b);
	return [...new Set([...listed.sort(rootFirst), ...extra])];
}

function units(file) {
	const result = [];
	let heading = '';
	let current;
	let fence;
	const flush = () => {
		if (current) result.push(current);
		current = undefined;
	};
	const lines = readFileSync(join(repo, file), 'utf8').split('\n');
	lines.forEach((line, index) => {
		const number = index + 1;
		if (fence) {
			current.text.push(line);
			if (line.trim().startsWith(fence)) {
				fence = undefined;
				flush();
			}
			return;
		}
		const fenceOpen = /^\s*(```|~~~)/.exec(line);
		if (fenceOpen) {
			flush();
			fence = fenceOpen[1];
			current = {file, line: number, heading, text: [line]};
			return;
		}
		const headingMatch = /^#{1,6}\s+(.*)$/.exec(line);
		if (headingMatch) {
			flush();
			heading = headingMatch[1].trim();
			return;
		}
		if (line.trim() === '' || /^\s*@\S+\s*$/.test(line) || /^\s*\|?\s*:?-{3,}/.test(line)) {
			flush();
			return;
		}
		const isTableRow = /^\s*\|/.test(line);
		const isHeaderRow = isTableRow && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1] ?? '');
		if (isHeaderRow) return;
		if (isTableRow || /^\s*([-*+]|\d+[.)])\s+/.test(line) || !current) {
			flush();
			current = {file, line: number, heading, text: [line]};
		} else {
			current.text.push(line);
		}
	});
	flush();
	return result;
}

function cell(text) {
	const flat = text.join(' ').replace(/\s+/g, ' ').trim().replace(/\|/g, '\\|');
	return flat.length > 160 ? `${flat.slice(0, 157)}...` : flat;
}

// Markdown files the sources link to, other than the sources themselves.
function linkedDocs(files) {
	const linked = new Map();
	for (const file of files) {
		const text = readFileSync(join(repo, file), 'utf8');
		for (const match of text.matchAll(/\]\(\s*<?((?:[^()\s>#]|\([^()\s]*\))+\.md)(?:#[^)\s]*)?>?\s*\)/g)) {
			if (/^[a-z][a-z0-9+.-]*:/i.test(match[1])) continue;
			const target = normalize(match[1].startsWith('/') ? match[1].slice(1) : join(dirname(file), match[1]));
			if (target.startsWith('..') || files.includes(target) || !existsSync(join(repo, target))) continue;
			if (!linked.has(target)) linked.set(target, file);
		}
	}
	return [...linked].sort(([a], [b]) => a.localeCompare(b));
}

function write() {
	const files = sources();
	const docs = linkedDocs(files);
	const all = [
		...files.flatMap(units),
		...docs.map(([doc, from]) => ({file: doc, line: 1, heading: '', text: [`whole doc, linked from ${from}`]})),
	];
	const out = [
		'# Agent rules inventory',
		'',
		`<!-- units: ${all.length} -->`,
		'',
		'Sources:',
		...files.map((file) => {
			const text = readFileSync(join(repo, file), 'utf8');
			return `- ${file}: ${text.trimEnd().split('\n').length} lines, ${statSync(join(repo, file)).size} bytes`;
		}),
		...(docs.length > 0
			? ['', 'Linked docs (one row each; name one as an argument to itemize it):', ...docs.map(([doc]) => `- ${doc}: ${statSync(join(repo, doc)).size} bytes`)]
			: []),
		'',
		'Destination: `root`, `doc <path>`, `folder <path>`, or `delete`. A `delete` needs a reason.',
		'',
		'| id | source | rule | destination | reason |',
		'| --- | --- | --- | --- | --- |',
		...all.map(
			(unit, index) =>
				`| ${index + 1} | ${unit.file}:${unit.line}${unit.heading ? ` (${unit.heading.replace(/\|/g, '\\|')})` : ''} | ${cell(unit.text)} |  |  |`,
		),
		'',
	].join('\n');
	const target = option('--out');
	if (target) {
		writeFileSync(target, out);
		console.log(`Wrote ${all.length} units from ${files.length} files to ${target}.`);
	} else {
		process.stdout.write(out);
	}
	return 0;
}

function check(file) {
	const text = readFileSync(file, 'utf8');
	const declared = Number(/<!-- units: (\d+) -->/.exec(text)?.[1]);
	const problems = [];
	const seen = new Set();
	const counts = {};
	for (const line of text.split('\n')) {
		const cells = line
			.split(/(?<!\\)\|/)
			.slice(1, -1)
			.map((value) => value.trim());
		if (!/^\d+[a-z]?$/.test(cells[0] ?? '')) continue;
		const [id, source, , destination = '', reason = ''] = cells;
		seen.add(Number.parseInt(id, 10));
		const match = /^(root|delete|doc|folder)(?:\s+`?([^`\s]+)`?)?$/.exec(destination);
		if (!match || ((match[1] === 'doc' || match[1] === 'folder') && !match[2])) {
			problems.push(`row ${id} (${source}): destination "${destination}" is not root, doc <path>, folder <path>, or delete`);
			continue;
		}
		counts[match[1]] = (counts[match[1]] ?? 0) + 1;
		if (match[1] === 'delete' && !reason) problems.push(`row ${id} (${source}): delete without a reason`);
		if (repoArg && match[2] && !existsSync(join(repo, match[2]))) {
			problems.push(`row ${id} (${source}): ${match[2]} does not exist in ${repo}`);
		}
	}
	if (!Number.isInteger(declared)) problems.push('no "<!-- units: N -->" line; regenerate the skeleton');
	for (let id = 1; id <= declared; id++) if (!seen.has(id)) problems.push(`row ${id} is missing`);
	console.log(`Rows by destination: ${JSON.stringify(counts)}`);
	for (const problem of problems) console.log(`error: ${problem}`);
	console.log(problems.length === 0 ? `All ${declared} units have a destination.` : `${problems.length} problems.`);
	return problems.length === 0 ? 0 : 1;
}
