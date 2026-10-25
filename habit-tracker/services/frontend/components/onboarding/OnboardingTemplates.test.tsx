// [review:need-review] PHASE-01/219-templates-in-onboarding
// summary: onboarding template step — offers the catalog, creates nothing until asked, reports what was added and what was skipped, can be dismissed and brought back

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Category, CategoryTemplate, CategoryTemplateApplyResponse } from '@/lib/api';
import type { TemplateClient } from '@/components/categories/TemplatePicker';
import OnboardingTemplates from './OnboardingTemplates';

const SUPPLEMENTS: CategoryTemplate = {
  key: 'supplements',
  name: 'Supplements',
  display_mode: 'checklist',
  streak_mode: 'build',
  added: false,
  fields: [{ name: 'Vitamin D', field_type: 'boolean', order: 1 }],
};

const WATER: CategoryTemplate = {
  key: 'water',
  name: 'Water',
  display_mode: 'form',
  streak_mode: 'build',
  added: false,
  fields: [{ name: 'Volume', field_type: 'number', order: 1, unit: 'ml' }],
};

function category(name: string): Category {
  return { id: 1, name, display_mode: 'form', streak_mode: 'build' } as Category;
}

function makeClient(response: CategoryTemplateApplyResponse) {
  const apply = mock<TemplateClient['applyTemplates']>(() => Promise.resolve(response));
  const client: TemplateClient = {
    listTemplates: () => Promise.resolve([SUPPLEMENTS, WATER]),
    applyTemplates: apply,
  };
  return { client, apply };
}

async function addTemplate(label: RegExp) {
  fireEvent.click(await screen.findByLabelText(label));
  fireEvent.click(screen.getByRole('button', { name: /add selected/i }));
}

afterEach(cleanup);

describe('OnboardingTemplates', () => {
  it('offers the catalog and creates nothing on its own', async () => {
    const { client, apply } = makeClient({ categories: [], skipped: [] });

    render(<OnboardingTemplates client={client} onOpenCategories={() => {}} />);

    expect(await screen.findByLabelText(/Supplements/)).toBeTruthy();
    expect(apply).not.toHaveBeenCalled();
  });

  it('names what was added after applying', async () => {
    const { client, apply } = makeClient({ categories: [category('Water')], skipped: [] });

    render(<OnboardingTemplates client={client} onOpenCategories={() => {}} />);
    await addTemplate(/Water/);

    const status = await screen.findByRole('status');
    expect(status.textContent).toContain('Water');
    expect(apply).toHaveBeenCalledWith(['water']);
    expect(screen.queryByText(/Пропущено/)).toBeNull();
  });

  it('tells the person which templates were skipped, by name', async () => {
    const { client } = makeClient({ categories: [], skipped: ['supplements'] });

    render(<OnboardingTemplates client={client} onOpenCategories={() => {}} />);
    await addTemplate(/Supplements/);

    const status = await screen.findByRole('status');
    expect(status.textContent).toContain('Пропущено');
    expect(status.textContent).toContain('Supplements');
    expect(status.textContent).not.toContain('Добавлено');
  });

  it('reports added and skipped together', async () => {
    const { client } = makeClient({ categories: [category('Water')], skipped: ['supplements'] });

    render(<OnboardingTemplates client={client} onOpenCategories={() => {}} />);
    await addTemplate(/Water/);

    const status = await screen.findByRole('status');
    expect(status.textContent).toContain('Добавлено');
    expect(status.textContent).toContain('Пропущено');
  });

  it('opens the categories list on request', async () => {
    const { client } = makeClient({ categories: [category('Water')], skipped: [] });
    const onOpenCategories = mock(() => {});

    render(<OnboardingTemplates client={client} onOpenCategories={onOpenCategories} />);
    await addTemplate(/Water/);
    fireEvent.click(await screen.findByRole('button', { name: /Открыть категории/ }));

    expect(onOpenCategories).toHaveBeenCalledTimes(1);
  });

  it('can be dismissed without creating anything, and brought back', async () => {
    const { client, apply } = makeClient({ categories: [], skipped: [] });

    render(<OnboardingTemplates client={client} onOpenCategories={() => {}} />);
    await screen.findByLabelText(/Supplements/);
    fireEvent.click(screen.getByRole('button', { name: /Пропустить шаблоны/ }));

    expect(screen.queryByLabelText(/Supplements/)).toBeNull();
    expect(apply).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /Показать шаблоны/ }));
    await waitFor(() => expect(screen.getByLabelText(/Supplements/)).toBeTruthy());
  });
});
