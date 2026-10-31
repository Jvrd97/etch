// [review:need-review] PHASE-03/264
// summary: swaps one method of an API object for the length of a test and hands back the way to put it back — assignment rather than `spyOn`, because a suite that mocked `@/lib/api` before may have left an object without that method, and `spyOn` then installs nothing

/** Replace `target[key]` with `impl`; call the returned function to restore the previous value. */
export function replaceMethod<T extends object, K extends keyof T>(
  target: T,
  key: K,
  impl: T[K]
): () => void {
  const original = target[key];
  target[key] = impl;
  return () => {
    target[key] = original;
  };
}
