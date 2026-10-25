// [review:need-review] PHASE-01/178-builtin-category-templates
// summary: the picker lists the catalog, applies only what the user ticked, shows already-added templates as taken and surfaces failures

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { CategoryTemplate, CategoryTemplateApplyResponse } from '@/lib/api';
import TemplatePicker, { type TemplateClient, type TemplatePickerProps } from './TemplatePicker';

const SUPPLEMENTS: CategoryTemplate = {
  key: 'supplements',
  name: 'Supplements',
  description: 'Tick off the supplements you took today.',
  display_mode: 'checklist',
  streak_mode: 'build',
  added: false,
  fields: [
    { name: 'Vitamin D', field_type: 'boolean', order: 1 },
    { name: 'Omega-3', field_type: 'boolean', order: 2 },
  ],
};

const WATER: CategoryTemplate = {
  key: 'water',
  name: 'Water',
  display_mode: 'form',
  streak_mode: 'build',
  added: false,
  fields: [{ name: 'Volume', field_type: 'number', order: 1, unit: 'ml' }],
};

const APPLIED: CategoryTemplateApplyResponse = { categories: [], skipped: [] };

function makeClient(templates: CategoryTemplate[]) {
  const list = mock(() => Promise.resolve(templates));
  const apply = mock<TemplateClient['applyTemplates']>(() => Promise.resolve(APPLIED));
  const client: TemplateClient = { listTemplates: list, applyTemplates: apply };
  return { client, list, apply };
}

afterEach(cleanup);

describe('TemplatePicker', () => {
  it('lists every template with its fields and applies nothing until asked', async () => {
    const { client, apply } = makeClient([SUPPLEMENTS, WATER]);

    render(<TemplatePicker client={client} onApplied={() => {}} />);

    expect(await screen.findByText('Supplements')).toBeTruthy();
    expect(screen.getByText('Water')).toBeTruthy();
    expect(screen.getByText(/Vitamin D/)).toBeTruthy();
    expect(apply).not.toHaveBeenCalled();
  });

  it('keeps the apply button disabled while nothing is ticked', async () => {
    const { client } = makeClient([SUPPLEMENTS]);

    render(<TemplatePicker client={client} onApplied={() => {}} />);
    await screen.findByText('Supplements');

    expect((screen.getByRole('button', { name: /add selected/i }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it('sends only the ticked keys and reports success', async () => {
    const { client, apply } = makeClient([SUPPLEMENTS, WATER]);
    const onApplied = mock<(result: CategoryTemplateApplyResponse) => void>(() => {});

    render(<TemplatePicker client={client} onApplied={onApplied} />);
    fireEvent.click(await screen.findByLabelText(/Supplements/));
    fireEvent.click(screen.getByRole('button', { name: /add selected/i }));

    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
    expect(apply).toHaveBeenCalledWith(['supplements']);
  });

  it('hands the catalog it showed to onApplied, so the caller can name skipped keys', async () => {
    const { client } = makeClient([SUPPLEMENTS, WATER]);
    const onApplied = mock<TemplatePickerProps['onApplied']>(() => {});

    render(<TemplatePicker client={client} onApplied={onApplied} />);
    fireEvent.click(await screen.findByLabelText(/Supplements/));
    fireEvent.click(screen.getByRole('button', { name: /add selected/i }));

    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
    expect(onApplied.mock.calls[0][1]).toEqual([SUPPLEMENTS, WATER]);
  });

  it('shows an already added template as taken and cannot tick it', async () => {
    const { client } = makeClient([{ ...SUPPLEMENTS, added: true }, WATER]);

    render(<TemplatePicker client={client} onApplied={() => {}} />);

    const taken = (await screen.findByLabelText(/Supplements/)) as HTMLInputElement;
    expect(taken.disabled).toBe(true);
    expect(screen.getByText(/already added/i)).toBeTruthy();
  });

  it('shows the failure and does not report success when applying fails', async () => {
    const { client, apply } = makeClient([SUPPLEMENTS]);
    apply.mockImplementation(() => Promise.reject(new Error('boom')));
    const onApplied = mock<(result: CategoryTemplateApplyResponse) => void>(() => {});

    render(<TemplatePicker client={client} onApplied={onApplied} />);
    fireEvent.click(await screen.findByLabelText(/Supplements/));
    fireEvent.click(screen.getByRole('button', { name: /add selected/i }));

    expect(await screen.findByText(/boom/)).toBeTruthy();
    expect(onApplied).not.toHaveBeenCalled();
  });

  it('shows the failure when the catalog cannot be loaded', async () => {
    const { client, list } = makeClient([]);
    list.mockImplementation(() => Promise.reject(new Error('offline')));

    render(<TemplatePicker client={client} onApplied={() => {}} />);

    expect(await screen.findByText(/offline/)).toBeTruthy();
  });
});
