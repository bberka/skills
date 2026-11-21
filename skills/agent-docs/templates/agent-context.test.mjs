import assert from 'node:assert/strict';
import {mkdirSync, mkdtempSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import process from 'node:process';
import {test} from 'node:test';
import {globToRegExp, grown, measure} from './agent-context.mjs';

test('globs match inside one segment or across folders', () => {
	assert.ok(globToRegExp('**/AGENTS.md').test('AGENTS.md'));
	assert.ok(globToRegExp('**/AGENTS.md').test('apps/web/AGENTS.md'));
	assert.ok(globToRegExp('docs/agents/**/*.md').test('docs/agents/ui.md'));
	assert.ok(!globToRegExp('docs/agents/*.md').test('docs/agents/old/ui.md'));
	assert.ok(!globToRegExp('AGENTS.md').test('apps/AGENTS.md'));
});

test('a file counts once, in the first matching group, and excluded files not at all', () => {
	const dir = mkdtempSync(join(tmpdir(), 'agent-context-'));
	const files = {'AGENTS.md': 10, 'apps/web/AGENTS.md': 4, 'docs/agents/ui.md': 7, '.claude/skills/x/AGENTS.md': 99};
	for (const [file, size] of Object.entries(files)) {
		mkdirSync(join(dir, file, '..'), {recursive: true});
		writeFileSync(join(dir, file), 'x'.repeat(size));
	}
	const cwd = process.cwd();
	process.chdir(dir);
	try {
		const groups = {'AGENTS.md': ['AGENTS.md'], '**/AGENTS.md': ['**/AGENTS.md'], 'docs/agents': ['docs/agents/**/*.md']};
		assert.deepEqual(measure(Object.keys(files), groups, ['.claude/**']), {
			'AGENTS.md': 10,
			'**/AGENTS.md': 4,
			'docs/agents': 7,
		});
	} finally {
		process.chdir(cwd);
	}
});

test('only a group larger than the base counts as growth', () => {
	assert.deepEqual(grown({a: 12, b: 5, c: 99}, {a: 10, b: 8}), ['a: 10 -> 12 bytes (+2)']);
});
