// [review:need-review] PHASE-03/109
// summary: unit tests for the bundle scanner, plus the standing invariant — no source file of this app reads a key-shaped NEXT_PUBLIC_ env var

import { afterAll, describe, expect, it } from 'bun:test';
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  collectTextFiles,
  filesLeakingSecret,
  filesReadingPublicSecretEnv,
} from './bundle-scan';

const SECRET = 'e3b0c44298fc1c149afbf4c8996fb924';
const workspace = mkdtempSync(join(tmpdir(), 'bundle-scan-'));

afterAll(() => rmSync(workspace, { recursive: true, force: true }));

function fixture(name: string, files: Record<string, string>): string {
  const root = join(workspace, name);
  mkdirSync(join(root, 'static'), { recursive: true });
  for (const [path, text] of Object.entries(files)) {
    writeFileSync(join(root, path), text);
  }
  return root;
}

describe('collectTextFiles', () => {
  it('reads the tree and keeps only the asked-for extensions', () => {
    const root = fixture('collect', {
      'page.js': 'const a = 1;',
      'static/chunk.js': 'const b = 2;',
      'icon.png': 'not text',
    });
    const found = collectTextFiles(root, ['.js']).map((file) => file.path);
    expect(found).toHaveLength(2);
    expect(found.every((path) => path.endsWith('.js'))).toBe(true);
  });

  it('walks past node_modules', () => {
    const root = fixture('skip', { 'page.js': 'ok' });
    mkdirSync(join(root, 'node_modules'), { recursive: true });
    writeFileSync(join(root, 'node_modules', 'dep.js'), SECRET);
    expect(filesLeakingSecret(collectTextFiles(root, ['.js']), SECRET)).toEqual([]);
  });
});

describe('filesLeakingSecret', () => {
  it('names the file that carries the key verbatim', () => {
    const root = fixture('leak', {
      'page.js': 'const clean = 1;',
      'static/chunk.js': `fetch('/api', {headers: {'X-API-Key': '${SECRET}'}})`,
    });
    expect(filesLeakingSecret(collectTextFiles(root, ['.js']), SECRET)).toEqual([
      join(root, 'static', 'chunk.js'),
    ]);
  });

  it('says nothing when the bundle is clean', () => {
    const root = fixture('clean', { 'page.js': "credentials: 'include'" });
    expect(filesLeakingSecret(collectTextFiles(root, ['.js']), SECRET)).toEqual([]);
  });

  it('refuses to scan for an empty secret instead of passing trivially', () => {
    expect(() => filesLeakingSecret([{ path: 'x.js', text: 'anything' }], '')).toThrow();
  });
});

describe('filesReadingPublicSecretEnv', () => {
  it('flags a build variable whose value would end up in the bundle', () => {
    const files = [
      { path: 'a.ts', text: "process.env.NEXT_PUBLIC_API_KEY" },
      { path: 'b.ts', text: "process.env.NEXT_PUBLIC_API_URL" },
      { path: 'c.ts', text: "process.env.API_PROXY_TARGET" },
    ];
    expect(filesReadingPublicSecretEnv(files)).toEqual(['a.ts']);
  });
});

// --- the standing invariant of this app -----------------------------------

const PROJECT_ROOT = join(import.meta.dir, '..');
const SOURCE_ROOTS = ['app', 'lib', 'components', 'hooks'];
const SOURCE_EXTENSIONS = ['.ts', '.tsx', '.js', '.mjs'];

describe('this frontend', () => {
  it('never reads a key-shaped NEXT_PUBLIC_ variable', () => {
    // The invariant that makes "no key in the bundle" impossible to break by a
    // later edit: whatever the key is, it can only reach the browser through a
    // build variable, and this app reads none. Its counterpart over the built
    // output is `bun run check:bundle`, which needs a build and the key value.
    const sources = SOURCE_ROOTS.map((root) => join(PROJECT_ROOT, root))
      .filter((root) => existsSync(root))
      .flatMap((root) => collectTextFiles(root, SOURCE_EXTENSIONS))
      // Tests are not bundled, and this very file spells the pattern out.
      .filter((file) => !file.path.includes('.test.'));
    expect(sources.length).toBeGreaterThan(0);
    expect(filesReadingPublicSecretEnv(sources)).toEqual([]);
  });
});
