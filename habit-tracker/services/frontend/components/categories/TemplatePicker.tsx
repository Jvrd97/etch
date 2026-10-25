'use client';
// [review:need-review] PHASE-01/178-builtin-category-templates
// summary: picker for the built-in category catalog; applies only the templates the user ticked, never on its own

import { useEffect, useState } from 'react';
import * as api from '@/lib/api';
import type { CategoryTemplate, CategoryTemplateApplyResponse } from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';

/** The two calls the picker needs; injectable so a test needs no network. */
export interface TemplateClient {
  listTemplates: () => Promise<CategoryTemplate[]>;
  applyTemplates: (keys: string[]) => Promise<CategoryTemplateApplyResponse>;
}

// Read at call time: a screen test that mocks '@/lib/api' with a fixed export
// set must still link this module.
const apiClient: TemplateClient = {
  listTemplates: () => api.categoriesAPI.listTemplates(),
  applyTemplates: (keys) => api.categoriesAPI.applyTemplates(keys),
};

const LOAD_TEMPLATES_ERROR = 'Failed to load templates';
const APPLY_TEMPLATES_ERROR = 'Failed to add templates';

interface TemplatePickerProps {
  client?: TemplateClient;
  onApplied: (result: CategoryTemplateApplyResponse) => void;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export default function TemplatePicker({ client = apiClient, onApplied }: TemplatePickerProps) {
  const [templates, setTemplates] = useState<CategoryTemplate[]>([]);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    client
      .listTemplates()
      .then((items) => {
        if (!cancelled) setTemplates(items);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorMessage(err, LOAD_TEMPLATES_ERROR));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const toggle = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const apply = async () => {
    setApplying(true);
    setError(null);
    try {
      onApplied(await client.applyTemplates([...selected]));
    } catch (err) {
      setError(errorMessage(err, APPLY_TEMPLATES_ERROR));
    } finally {
      setApplying(false);
    }
  };

  return (
    <section
      aria-label="Category templates"
      className="bg-card border border-white/5 rounded-3xl p-6 space-y-4"
    >
      <div>
        <h2 className="text-lg font-medium text-text-primary">Start from a template</h2>
        <p className="text-sm text-text-secondary">
          Pick what you want to track. Each one becomes an ordinary category you can rename,
          extend or delete.
        </p>
      </div>

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {loading ? (
        <p className="text-sm text-text-disabled">Loading templates...</p>
      ) : (
        <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {templates.map((template) => (
            <li key={template.key}>
              <label
                className={`flex items-start gap-3 bg-surface border border-white/5 rounded-2xl p-4 ${
                  template.added ? 'opacity-60' : 'cursor-pointer hover:border-white/10'
                }`}
              >
                <input
                  type="checkbox"
                  checked={selected.has(template.key)}
                  disabled={template.added}
                  onChange={() => toggle(template.key)}
                  className="mt-1 w-4 h-4 accent-[#B8FF36]"
                />
                <span className="min-w-0 space-y-1">
                  <span className="block text-text-primary font-medium">{template.name}</span>
                  {template.description && (
                    <span className="block text-sm text-text-secondary">
                      {template.description}
                    </span>
                  )}
                  <span className="block text-xs text-text-disabled">
                    {template.fields.map((field) => field.name).join(', ')}
                  </span>
                  {template.added && (
                    <span className="inline-block px-2 py-0.5 rounded-full text-xs bg-white/5 text-text-secondary">
                      Already added
                    </span>
                  )}
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}

      <button
        type="button"
        onClick={() => void apply()}
        disabled={selected.size === 0 || applying}
        className="px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 disabled:opacity-50 disabled:hover:translate-y-0"
      >
        {applying ? 'Adding...' : 'Add selected'}
      </button>
    </section>
  );
}
