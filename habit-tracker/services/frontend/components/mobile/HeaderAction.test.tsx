// [review:need-review] PHASE-01/49-device-acceptance-checklist
// summary: tests for MobileHeaderAction — the action lands in the header slot when the shell provides one, stays in place when it does not, and never floats over the list

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import MobileHeaderAction, {
  MOBILE_HEADER_ACTION_SLOT_ID,
  MobileHeaderActionSlot,
} from './HeaderAction';

afterEach(() => {
  cleanup();
});

describe('MobileHeaderAction', () => {
  it('renders into the header slot when the shell provides one', () => {
    render(
      <div>
        <header>
          <MobileHeaderActionSlot />
        </header>
        <main>
          <MobileHeaderAction label="New entry" onClick={() => {}} />
        </main>
      </div>
    );

    const button = screen.getByRole('button', { name: 'New entry' });
    expect(button.closest(`#${MOBILE_HEADER_ACTION_SLOT_ID}`)).not.toBeNull();
    expect(button.closest('main')).toBeNull();
  });

  it('stays where it was written when no slot exists', () => {
    render(<MobileHeaderAction label="New entry" onClick={() => {}} />);
    expect(screen.getByRole('button', { name: 'New entry' })).toBeDefined();
  });

  it('fires its action on tap', () => {
    const onClick = mock(() => {});
    render(<MobileHeaderAction label="New entry" onClick={onClick} />);
    fireEvent.click(screen.getByRole('button', { name: 'New entry' }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('never floats above the content it would cover', () => {
    render(<MobileHeaderAction label="New entry" onClick={() => {}} />);
    // The bug this component exists to fix: a `fixed` disc in the bottom-right
    // corner sits exactly on the last card's own buttons.
    expect(screen.getByRole('button', { name: 'New entry' }).className).not.toContain('fixed');
  });

  it('keeps a 44pt tap target', () => {
    render(<MobileHeaderAction label="New entry" onClick={() => {}} />);
    const button = screen.getByRole('button', { name: 'New entry' });
    expect(button.style.minHeight).toBe('44px');
    expect(button.style.minWidth).toBe('44px');
  });
});
