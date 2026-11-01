// [review:need-review] #311
// summary: the one read of the category list every screen shares through the read cache — the active list and the unfiltered one under their own keys, a read already out joined instead of repeated, and the invalidation a category write calls

import * as api from '@/lib/api';
import type { Category } from '@/lib/api';
import { fetchQuery, invalidateQueries } from '@/lib/query-cache';

const CATEGORIES_PREFIX = 'categories:';

/** The cache key of the active list (`activeOnly`) or of every category. */
export function categoriesKey(activeOnly: boolean): string {
  return `${CATEGORIES_PREFIX}${activeOnly ? 'active' : 'all'}`;
}

/**
 * The category list, read once for all the readers of one moment.
 *
 * Seven hooks need it and a page mounts several of them together: they join the
 * request already out. A read with none out asks the server — the caller is a
 * load or a reload, and a list a write has just changed must not come from memory.
 * The namespace import is read at call time, so suites that mock `@/lib/api`
 * still reach their own `categoriesAPI`.
 */
export function readCategories(activeOnly = true): Promise<Category[]> {
  return fetchQuery(categoriesKey(activeOnly), () => api.categoriesAPI.getAll(activeOnly));
}

/** A category was created, changed or deleted: every cached list is stale. */
export function invalidateCategories(): void {
  invalidateQueries(CATEGORIES_PREFIX);
}
