// [review:need-review] PHASE-03/197
// summary: tests for useDeletedConversation — after the open conversation is deleted the screen is kept empty even while the address still names it, a conversation picked afterwards lifts the hold, and the same holds when the deleted one was the latest shown without any address

import { afterEach, describe, expect, it } from 'bun:test';
import { act, cleanup, renderHook } from '@testing-library/react';
import { useDeletedConversation } from './useDeletedConversation';

afterEach(cleanup);

function mount(linked: number | null) {
  return renderHook(({ id }: { id: number | null }) => useDeletedConversation(id), {
    initialProps: { id: linked },
  });
}

describe('useDeletedConversation', () => {
  it('passes the link through while nothing has been deleted', () => {
    const view = mount(5);

    expect(view.result.current.conversationId).toBe(5);
    expect(view.result.current.stayEmpty).toBe(false);
  });

  it('stops naming the deleted conversation at once, before the router has moved', () => {
    // Пока роутер меняет адрес, ссылка ещё называет удалённый разговор, и
    // открывать его заново нельзя.
    const view = mount(5);

    act(() => view.result.current.markDeleted(5));

    expect(view.result.current.conversationId).toBeNull();
    expect(view.result.current.stayEmpty).toBe(true);
  });

  it('stays empty once the address is cleared', () => {
    const view = mount(5);
    act(() => view.result.current.markDeleted(5));

    view.rerender({ id: null });

    expect(view.result.current.conversationId).toBeNull();
    expect(view.result.current.stayEmpty).toBe(true);
  });

  it('lets go when another conversation is picked', () => {
    const view = mount(5);
    act(() => view.result.current.markDeleted(5));
    view.rerender({ id: null });

    view.rerender({ id: 7 });

    expect(view.result.current.conversationId).toBe(7);
    expect(view.result.current.stayEmpty).toBe(false);
  });

  it('holds the same way when the deleted conversation was shown without an address', () => {
    const view = mount(null);

    act(() => view.result.current.markDeleted(3));

    expect(view.result.current.conversationId).toBeNull();
    expect(view.result.current.stayEmpty).toBe(true);

    view.rerender({ id: 7 });
    expect(view.result.current.conversationId).toBe(7);
    expect(view.result.current.stayEmpty).toBe(false);
  });

  it('does not come back to the deleted conversation if the hold was lifted and the link is gone', () => {
    const view = mount(5);
    act(() => view.result.current.markDeleted(5));
    view.rerender({ id: 7 });
    view.rerender({ id: null });

    // Без ссылки экран снова берёт свежий разговор: человек сам ушёл из пустого.
    expect(view.result.current.stayEmpty).toBe(false);
    expect(view.result.current.conversationId).toBeNull();
  });
});
