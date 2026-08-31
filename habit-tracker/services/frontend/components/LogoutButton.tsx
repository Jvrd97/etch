'use client';
// [review:need-review] PHASE-03/109
// summary: "Выйти" — drops the session cookie on the server and lands on the login screen; one component for both shells so the two cannot drift

import { useState } from 'react';
import { LogOut } from 'lucide-react';
import { authAPI } from '@/lib/api';
import { LOGIN_PATH } from '@/lib/auth';

/**
 * Выход.
 *
 * Стирает куку сервер — браузер её не видит и стереть не может. Поэтому ошибка
 * запроса тут не проглатывается: если `DELETE` не дошёл, сессия жива, и
 * притворяться вышедшим значит соврать. Навигация — жёсткая, чтобы ни один
 * экран не остался с данными, загруженными под этой сессией.
 */
export default function LogoutButton({ className }: { className?: string }) {
  const [leaving, setLeaving] = useState(false);

  const handleLogout = async () => {
    if (leaving) return;
    setLeaving(true);
    try {
      await authAPI.logout();
      window.location.assign(LOGIN_PATH);
    } catch {
      // Кука на сервере не стёрта — молча «выйти» нельзя, кнопка возвращается.
      setLeaving(false);
    }
  };

  return (
    <button
      type="button"
      onClick={handleLogout}
      disabled={leaving}
      title="Выйти"
      aria-label="Выйти"
      className={
        className ??
        'inline-flex items-center gap-2 px-3 py-2 rounded-full text-sm font-medium text-text-secondary hover:text-text-primary hover:bg-white/5 transition-colors duration-200 disabled:opacity-40'
      }
    >
      <LogOut className="w-4 h-4" strokeWidth={2} />
      <span className="hidden sm:inline">Выйти</span>
    </button>
  );
}
