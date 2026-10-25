// [review:need-review] PHASE-03/164
// summary: turns the agent status into the banners of the day screen — one for silence (and only that one for a silent agent), one for a refused Accessibility (not for an unknown one), one for the titles switch worded as a setting — with the words, the link and the key each one needs

import type { AgentStatus, AgentStatusItem } from '@/lib/api';

export type AgentBannerKind = 'silent' | 'accessibility' | 'titles_off';

export interface AgentBanner {
  /** Stable across renders: the agent and the cause. */
  key: string;
  kind: AgentBannerKind;
  title: string;
  body: string;
  action: { label: string; href: string } | null;
  /** Which mac, when there are several; null for a single one. */
  agentLabel: string | null;
}

const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
const HOURS_PER_DAY = 24;
const AGENT_LABEL_LENGTH = 8;
const TITLE_RULES_HREF = '/agent/title-rules';

export const SILENT_BANNER_NOTE =
  'Интервалы за это время могут отсутствовать: пока агент выключен, он ничего не собирает, а без сети досылает накопленное после возвращения.';
export const SILENT_BANNER_ACTION =
  'Проверьте, что Habit Agent запущен на маке (значок в строке меню), и нажмите «Начать сбор».';
export const ACCESSIBILITY_BANNER_TITLE = 'У агента нет доступа Accessibility';
export const ACCESSIBILITY_BANNER_BODY =
  'Заголовки окон не собираются, интервалы приходят урезанными: только приложение и время. Включите Habit Agent в Системных настройках: Конфиденциальность и безопасность, Универсальный доступ.';
export const TITLES_OFF_BANNER_TITLE = 'Заголовки окон выключены';
export const TITLES_OFF_NOT_AN_ERROR = 'Это настройка, а не сбой';
export const TITLES_OFF_BANNER_BODY = `${TITLES_OFF_NOT_AN_ERROR}: рубильник заголовков выключен, интервалы приходят без заголовков, и в списке «где прошёл день» они пустые.`;
export const TITLES_OFF_ACTION_LABEL = 'Правила заголовков';

/** «45 мин», «3 ч», «3 ч 10 мин», «1 дн 2 ч»: the largest unit and the one under it. */
export function formatSilence(seconds: number): string {
  const totalMinutes = Math.max(1, Math.floor(seconds / SECONDS_PER_MINUTE));
  const totalHours = Math.floor(totalMinutes / MINUTES_PER_HOUR);
  const minutes = totalMinutes % MINUTES_PER_HOUR;
  if (totalHours === 0) return `${totalMinutes} мин`;
  const days = Math.floor(totalHours / HOURS_PER_DAY);
  const hours = totalHours % HOURS_PER_DAY;
  if (days > 0) return hours > 0 ? `${days} дн ${hours} ч` : `${days} дн`;
  return minutes > 0 ? `${hours} ч ${minutes} мин` : `${hours} ч`;
}

function bannersOf(agent: AgentStatusItem, label: string | null): AgentBanner[] {
  const make = (
    kind: AgentBannerKind,
    title: string,
    body: string,
    action: AgentBanner['action'] = null
  ): AgentBanner => ({
    key: `${agent.agent_id}:${kind}`,
    kind,
    title,
    body,
    action,
    agentLabel: label,
  });

  // A silent agent's flags were true when it last spoke; saying more than that
  // it is silent would put old news on the screen as current.
  if (agent.is_silent) {
    return [
      make(
        'silent',
        `Агент молчит ${formatSilence(agent.silent_for_seconds)}`,
        `${SILENT_BANNER_NOTE} ${SILENT_BANNER_ACTION}`
      ),
    ];
  }
  const banners: AgentBanner[] = [];
  // Only an answer is news: null means the agent does not know yet (it does not
  // collect window titles before #156/#157), and the banner comes by itself once
  // the agent starts to send true or false.
  if (agent.accessibility_granted === false) {
    banners.push(make('accessibility', ACCESSIBILITY_BANNER_TITLE, ACCESSIBILITY_BANNER_BODY));
  }
  if (agent.titles_enabled === false) {
    banners.push(
      make('titles_off', TITLES_OFF_BANNER_TITLE, TITLES_OFF_BANNER_BODY, {
        label: TITLES_OFF_ACTION_LABEL,
        href: TITLE_RULES_HREF,
      })
    );
  }
  return banners;
}

/** Every banner the day screen owes the person, in the order of the agents. */
export function bannersFor(status: AgentStatus): AgentBanner[] {
  const several = status.agents.length > 1;
  return status.agents.flatMap((agent) =>
    bannersOf(agent, several ? agent.agent_id.slice(0, AGENT_LABEL_LENGTH) : null)
  );
}
