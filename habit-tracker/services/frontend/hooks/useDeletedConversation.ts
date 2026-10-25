'use client';
// [review:need-review] PHASE-03/197
// summary: what a chat screen does with its address once the open conversation is deleted — it stops naming that conversation at once, keeps the screen empty instead of opening or creating another, and lets go when the reader picks one; shared by /chat and /m/chat so the subtle ordering is written once

import { useState } from 'react';

export interface DeletedConversation {
  /** Разговор, который экран открывает: из ссылки, пока она не называет удалённый. */
  conversationId: number | null;
  /** True, пока после удаления человек не выбрал другой: сам экран ничего не открывает. */
  stayEmpty: boolean;
  /** Открытый разговор удалён. */
  markDeleted: (id: number) => void;
}

/**
 * Состояние «открытый разговор удалён, другой ещё не выбран».
 *
 * Помнится id удалённого, а не флаг «был удалён»: пока роутер меняет адрес,
 * ссылка ещё называет удалённый разговор, и флаг сбросился бы раньше, чем адрес
 * очистится, — экран тут же открыл бы свежий или завёл новый. Когда же свежий
 * разговор показан без ссылки, адрес после удаления вообще не меняется, и держит
 * пустой экран только этот id.
 *
 * Сброс — прямо в рендере, тем способом, который React предлагает вместо
 * эффекта: выбор другого разговора обязан снять запрет в том же кадре.
 */
export function useDeletedConversation(linkedId: number | null): DeletedConversation {
  const [deletedId, setDeletedId] = useState<number | null>(null);
  if (deletedId !== null && linkedId !== null && linkedId !== deletedId) {
    setDeletedId(null);
  }
  return {
    conversationId: linkedId === deletedId ? null : linkedId,
    stayEmpty: deletedId !== null,
    markDeleted: setDeletedId,
  };
}
