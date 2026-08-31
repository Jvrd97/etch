// [review:need-review] PHASE-03/109
// summary: the grep invariant of the ticket, as a function — walk a directory, report files that carry a secret verbatim or read a key-shaped NEXT_PUBLIC_ env var

/**
 * Проверка «ключа в бандле нет».
 *
 * Next.js собирается статически: всё, что попало в `NEXT_PUBLIC_*`, вшивается
 * в JavaScript и уезжает в каждую вкладку. Поэтому у `#109` два инварианта, и
 * оба живут здесь функциями, а не разовым `grep` в чьей-то консоли:
 *
 * 1. в собранном `.next` нет значения ключа — ищется дословно;
 * 2. в исходниках нет чтения переменной вида `NEXT_PUBLIC_*KEY`, `*SECRET`,
 *    `*TOKEN` — то есть первый инвариант нельзя нарушить будущей правкой.
 *
 * Второй сильнее первого: он не требует ни сборки, ни знания текущего ключа, и
 * поэтому гоняется на каждом `bun test`.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

/** Имя переменной сборки, которая уехала бы в браузер вместе с секретом. */
export const PUBLIC_SECRET_ENV_PATTERN = /NEXT_PUBLIC_[A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD)/;

/** Каталоги, в которые заглядывать бессмысленно: чужой код и кеши сборки. */
const SKIPPED_DIRECTORIES = new Set(['node_modules', '.git', 'cache']);

/** Один прочитанный файл. Отделяет чтение диска от правила, которое проверяется. */
export interface ScannedFile {
  path: string;
  text: string;
}

/**
 * Прочитать дерево файлов с указанными расширениями.
 *
 * Нечитаемое как текст (картинки, шрифты) отсеивается расширением, а не
 * попыткой декодировать: бинарь, декодированный в UTF-8 с заменами, дал бы
 * ложное «чисто» на ровном месте.
 */
export function collectTextFiles(root: string, extensions: readonly string[]): ScannedFile[] {
  const collected: ScannedFile[] = [];
  const walk = (directory: string): void => {
    for (const name of readdirSync(directory)) {
      if (SKIPPED_DIRECTORIES.has(name)) continue;
      const path = join(directory, name);
      if (statSync(path).isDirectory()) {
        walk(path);
        continue;
      }
      if (!extensions.some((extension) => name.endsWith(extension))) continue;
      collected.push({ path, text: readFileSync(path, 'utf8') });
    }
  };
  walk(root);
  return collected;
}

/** Файлы, в которых секрет лежит дословно. Пустой список — инвариант держится. */
export function filesLeakingSecret(files: readonly ScannedFile[], secret: string): string[] {
  if (secret.length === 0) throw new Error('refusing to scan for an empty secret');
  return files.filter((file) => file.text.includes(secret)).map((file) => file.path);
}

/** Файлы, читающие переменную сборки, значение которой стало бы частью бандла. */
export function filesReadingPublicSecretEnv(files: readonly ScannedFile[]): string[] {
  return files
    .filter((file) => PUBLIC_SECRET_ENV_PATTERN.test(file.text))
    .map((file) => file.path);
}
