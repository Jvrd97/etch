// [review:need-review] PHASE-03/109
// summary: build-time check — fails when the built .next carries the API key verbatim, and fails just as loudly when there is no build to look at

/**
 * «Ключа в бандле нет» — проверкой, а не разовым `grep` в чьей-то консоли.
 *
 * Запускается после сборки:
 *
 *     API_KEY=<ключ> bun run build && API_KEY=<ключ> bun run check:bundle
 *
 * Отсутствие `.next` — тоже провал. Проверка, которая молча зеленеет, когда
 * смотреть не на что, хуже отсутствующей: она создаёт уверенность.
 */

import { existsSync } from 'node:fs';
import { collectTextFiles, filesLeakingSecret } from '../lib/bundle-scan';

const BUILD_DIR = '.next';
const BUNDLE_EXTENSIONS = ['.js', '.mjs', '.json', '.html', '.css', '.map'];

function fail(message: string): never {
  console.error(`check-bundle: ${message}`);
  process.exit(1);
}

const secret = process.argv[2] ?? process.env.API_KEY ?? '';
if (secret.length === 0) {
  fail('no key to look for — pass it as an argument or in API_KEY');
}
if (!existsSync(BUILD_DIR)) {
  fail(`no ${BUILD_DIR} to scan — run \`bun run build\` first`);
}

const leaks = filesLeakingSecret(collectTextFiles(BUILD_DIR, BUNDLE_EXTENSIONS), secret);
if (leaks.length > 0) {
  // The key itself is never printed: this output ends up in CI logs.
  fail(`the API key is present in ${leaks.length} built file(s):\n  ${leaks.join('\n  ')}`);
}

console.log(`check-bundle: no key in ${BUILD_DIR}`);
