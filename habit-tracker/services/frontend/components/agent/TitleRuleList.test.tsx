// [review:need-review] PHASE-03/158
// summary: component tests of the title-privacy screen — the arrows send the whole new order and go flat at the ends, a rule that fired on nothing reads «0 срабатываний», the kill switch carries the warning that nothing already sent is erased, and an empty policy says the default is deny

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { AgentSettings, TitleRule } from '@/lib/api';
import {
  DOWN_LABEL,
  EMPTY_POLICY_TEXT,
  KILL_SWITCH_WARNING,
  ORDER_HINT,
  UP_LABEL,
  actionLabel,
  hitsLine,
  matchKindLabel,
} from '@/lib/title-rules';

function rule(overrides: Partial<TitleRule> = {}): TitleRule {
  return {
    id: 1,
    ord: 0,
    match_kind: 'bundle_prefix',
    pattern: 'com.1password',
    action: 'drop',
    note: 'менеджер паролей',
    is_active: true,
    hits_7d: 3,
    ...overrides,
  };
}

const reordered = mock((_: number[]) => Promise.resolve());
const switched = mock((_: boolean) => Promise.resolve());

function withPolicy(rules: TitleRule[], settings: AgentSettings | null) {
  mock.module('@/hooks/useTitleRules', () => ({
    LOAD_RULES_ERROR: 'Не удалось загрузить правила заголовков',
    useTitleRules: () => ({
      rules,
      settings,
      loading: false,
      saving: false,
      error: null,
      add: () => Promise.resolve(),
      toggle: () => Promise.resolve(),
      remove: () => Promise.resolve(),
      move: (id: number, delta: number) => {
        const order = rules.map((row) => row.id);
        const from = order.indexOf(id);
        order.splice(from + delta, 0, ...order.splice(from, 1));
        return reordered(order);
      },
      setTitlesEnabled: switched,
    }),
  }));
}

const ON: AgentSettings = { titles_enabled: true, sampling_seconds: 5 };

afterEach(() => {
  cleanup();
  reordered.mockClear();
  switched.mockClear();
});

describe('подписи', () => {
  it('переводят словари на русский', () => {
    expect(matchKindLabel('bundle_prefix')).toBe('приложения с началом');
    expect(actionLabel('drop')).toBe('не сохранять');
  });

  it('считают срабатывания и склоняют их', () => {
    expect(hitsLine(rule({ hits_7d: 0 }))).toBe('за 7 дней: 0 срабатываний');
    expect(hitsLine(rule({ hits_7d: 1 }))).toBe('за 7 дней: 1 срабатывание');
    expect(hitsLine(rule({ hits_7d: 3 }))).toBe('за 7 дней: 3 срабатывания');
  });
});

describe('экран правил', () => {
  it('говорит, что порядок — это смысл', async () => {
    withPolicy([rule()], ON);
    const { default: TitleRuleList } = await import('./TitleRuleList');
    render(<TitleRuleList />);
    expect(screen.getByText(ORDER_HINT)).toBeTruthy();
  });

  it('перестановка едет целым порядком', async () => {
    withPolicy([rule({ id: 1 }), rule({ id: 2, pattern: 'com.google.Chrome' })], ON);
    const { default: TitleRuleList } = await import('./TitleRuleList');
    render(<TitleRuleList />);
    fireEvent.click(screen.getAllByLabelText(DOWN_LABEL)[0]);
    expect(reordered).toHaveBeenCalledWith([2, 1]);
  });

  it('стрелки на краях уровня плоские', async () => {
    withPolicy([rule({ id: 1 }), rule({ id: 2, pattern: 'com.google.Chrome' })], ON);
    const { default: TitleRuleList } = await import('./TitleRuleList');
    render(<TitleRuleList />);
    const up = screen.getAllByLabelText(UP_LABEL);
    const down = screen.getAllByLabelText(DOWN_LABEL);
    expect((up[0] as HTMLButtonElement).disabled).toBe(true);
    expect((down[1] as HTMLButtonElement).disabled).toBe(true);
  });

  it('правило, не сработавшее ни разу, показано нулём', async () => {
    withPolicy([rule({ hits_7d: 0 })], ON);
    const { default: TitleRuleList } = await import('./TitleRuleList');
    render(<TitleRuleList />);
    expect(screen.getByText(/за 7 дней: 0 срабатываний/)).toBeTruthy();
  });

  it('пустая политика говорит, что умолчание запрещающее', async () => {
    withPolicy([], ON);
    const { default: TitleRuleList } = await import('./TitleRuleList');
    render(<TitleRuleList />);
    expect(screen.getByText(EMPTY_POLICY_TEXT)).toBeTruthy();
  });
});

describe('рубильник', () => {
  it('предупреждает, что уже уехавшее остаётся', async () => {
    withPolicy([rule()], ON);
    const { default: TitleRuleList } = await import('./TitleRuleList');
    render(<TitleRuleList />);
    expect(screen.getByText(KILL_SWITCH_WARNING)).toBeTruthy();
  });

  it('выключает сбор заголовков', async () => {
    withPolicy([rule()], ON);
    const { default: TitleRuleList } = await import('./TitleRuleList');
    render(<TitleRuleList />);
    fireEvent.click(screen.getByText('выключить', { selector: 'button.text-sm' }));
    expect(switched).toHaveBeenCalledWith(false);
  });

  it('включает обратно, когда сбор выключен', async () => {
    withPolicy([rule()], { titles_enabled: false, sampling_seconds: 5 });
    const { default: TitleRuleList } = await import('./TitleRuleList');
    render(<TitleRuleList />);
    fireEvent.click(screen.getByText('включить', { selector: 'button.text-sm' }));
    expect(switched).toHaveBeenCalledWith(true);
  });
});
