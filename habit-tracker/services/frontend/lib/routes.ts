// [review:need-review] PHASE-01/73-daily-summary-metrics-vertical, PHASE-03/86, PHASE-03/93, PHASE-03/94, PHASE-03/111, PHASE-03/118, PHASE-03/125, PHASE-03/134, PHASE-03/152, PHASE-03/123, PHASE-03/nav-drawer
// summary: screens now carry `section` (День/Данные/Настройка) and `inHeader`, from which the desktop drawer and its two header anchors are derived; `isActiveRoute` marks a screen on its detail routes too
// summary: single registry of app screens — desktop nav, mobile tab bar, "More" list, mobile header titles and the mobile-route whitelist are all derived from it; every screen but Chat has a mobile twin (#118), Categories owns its nested detail route, Day summary/Goals/Roles/Journal/Table/Insights/Onboarding/Chat reached through "More"; Life owns the timeline and Week its dated detail route
// summary: single registry of app screens — desktop nav, mobile tab bar, "More" list, mobile header titles and the mobile-route whitelist are all derived from it; every screen has a mobile twin, Categories owns its nested detail route, Day summary/Goals/Journal/Table/Insights/Onboarding/Chat/Quick marks reached through "More"

/**
 * One screen of the app, described once for every navigation surface.
 *
 * Deliberately icon-free: this module is imported by server-only code
 * (`app/manifest.ts`), so it must stay clear of React and lucide. The id maps
 * to a glyph in `components/route-icons`.
 */
export interface AppRoute {
  /** Stable identifier, independent of the visible label. */
  id: string;
  /** Label shown in the nav, the tab bar and the mobile header. */
  name: string;
  /** Desktop route; the mobile twin is derived by `lib/view-mode`. */
  href: string;
  /** True once the screen has a real `/m` version. */
  hasMobile: boolean;
  /**
   * True when that `/m` version also serves the routes nested below `href` —
   * `/categories/12` as well as `/categories`. Kept separate from `hasMobile`
   * because most screens are flat: whitelisting `/today/12` would send the user
   * to a mobile route that does not exist. Meaningless without `hasMobile`.
   */
  hasMobileNested: boolean;
  /** Slot in the mobile tab bar (lower comes first), or null when it lives under "More". */
  inTabBar: number | null;
  /** Meaning group the desktop drawer files the screen under. */
  section: AppRouteSection;
  /**
   * True for the screens the desktop header shows without opening the drawer.
   *
   * The desktop counterpart of `inTabBar`, and deliberately a flag rather than a
   * slot: the header holds two anchors, and their order is the registry's.
   */
  inHeader: boolean;
}

/**
 * Meaning group of a screen, which is what the desktop drawer sorts by.
 *
 * The axis is how often the screen is opened, because that is the question the
 * reader actually asks the navigation. `day` is what a day is made of and is
 * opened daily; `data` is what accumulated and is opened to be read or picked
 * apart; `setup` is the directories and the canon, edited about once a month.
 */
export type AppRouteSection = 'day' | 'data' | 'setup';

/** Group headings, in the order the drawer prints them. */
export const SECTION_ORDER: readonly AppRouteSection[] = ['day', 'data', 'setup'];

export const SECTION_NAMES: Record<AppRouteSection, string> = {
  day: 'День',
  data: 'Данные',
  setup: 'Настройка',
};

/**
 * URL prefix owned by the mobile instance (`app/m/*`). It lives here rather
 * than in `lib/view-mode` because the registry itself has to spell mobile
 * hrefs, and `lib/view-mode` already imports this module — `view-mode`
 * re-exports it so the path helpers stay the one import consumers need.
 */
export const MOBILE_PATH_PREFIX = '/m';

/** Route of the mobile-only "More" screen. */
export const MORE_PATH = `${MOBILE_PATH_PREFIX}/more`;

/** Id of the mobile-only "More" tab, which has no entry in `APP_ROUTES`. */
export const MORE_ROUTE_ID = 'more';

/**
 * Address the app opens on: the bookmark, the typed host, the PWA icon.
 *
 * Today rather than the dashboard, and named here rather than spelled in each
 * of the three places, because the cold path is «вкладка открыта, отметить
 * воду»: every click of navigation before the buttons is paid on every single
 * open of the app.
 */
export const HOME_PATH = '/today';

/** Root of the desktop shell, which redirects to `HOME_PATH`. */
export const ROOT_PATH = '/';

/**
 * The dashboard's own address, off the root since #123.
 *
 * Named because two screens link to it by hand — the nav entry comes from the
 * registry, but the empty state of Insights sends the reader to the generator
 * that lives on the dashboard.
 */
export const DASHBOARD_PATH = '/dashboard';

/** Every screen, in desktop navigation order. */
export const APP_ROUTES: readonly AppRoute[] = [
  {
    id: 'dashboard',
    name: 'Dashboard',
    // Своим адресом, а не корневым (#123): корень уводит на Today, и дашборд,
    // оставшийся на `/`, стал бы экраном, до которого нет ссылки.
    href: DASHBOARD_PATH,
    hasMobile: true,
    hasMobileNested: false,
    inTabBar: 2,
    // «Данные»: сводка читается по накопленному, а не пишется в течение дня.
    section: 'data',
    inHeader: false,
  },
  {
    id: 'today',
    name: 'Today',
    href: '/today',
    hasMobile: true,
    hasMobileNested: false,
    inTabBar: 0,
    // «День»: тот самый экран, ради которого вкладка открыта.
    section: 'day',
    inHeader: true,
  },
  {
    id: 'day',
    name: 'Day',
    href: '/day',
    hasMobile: true,
    // `/day/2026-08-30` is a real screen on both shells, and the bare `/day`
    // is the same screen for today — the nesting flag is what carries the date
    // across when the reader switches shells.
    hasMobileNested: true,
    // Under "More": the day screen is opened on purpose, from a link with a
    // date on it, and the tab bar's five slots are already spoken for.
    inTabBar: null,
    // «День»: день целиком — план, отметки, вердикт.
    section: 'day',
    inHeader: false,
  },
  {
    id: 'life',
    name: 'Life',
    href: '/life',
    hasMobile: true,
    hasMobileNested: false,
    // Under "More": the timeline is opened to look at a stretch of days, which
    // is a weekly act rather than a daily one, and the tab bar's five slots are
    // already spoken for.
    inTabBar: null,
    // «День»: таймлайн отвечает на тот же вопрос «как прошёл отрезок жизни».
    section: 'day',
    inHeader: false,
  },
  {
    id: 'week',
    name: 'Week',
    // The bare `/week` is not a screen: a week is opened by its code, from the
    // timeline or from a link inside a plan. The entry stays in the registry
    // because that is what gives `/week/2026-W35` a mobile twin at all.
    href: '/week',
    hasMobile: true,
    hasMobileNested: true,
    inTabBar: null,
    // «День»: неделя — это отрезок дней, а не таблица.
    section: 'day',
    inHeader: false,
  },
  {
    id: 'goals',
    name: 'Goals',
    href: '/goals',
    hasMobile: true,
    hasMobileNested: false,
    // Under "More": the goals are read when a quarter turns or a milestone
    // closes, not several times a day, and the tab bar's five slots are already
    // spoken for.
    inTabBar: null,
    // «Настройка»: цели задают рамку, по которой судится день, и правятся,
    // когда поворачивается квартал, — это канон, а не накопленные данные.
    section: 'setup',
    inHeader: false,
  },
  {
    id: 'roles',
    name: 'Roles',
    href: '/roles',
    hasMobile: true,
    // `/roles/rules` — настоящий экран на обеих оболочках (`#139`), и вложенность
    // здесь именно затем, чтобы переход между ними не терял его.
    hasMobileNested: true,
    // Under "More": minutes and acts are written when a piece of work ends, not
    // several times an hour, and the tab bar's five slots are already spoken
    // for.
    inTabBar: null,
    // «Данные»: минуты и акты — накопленное по работе, его читают разбором.
    section: 'data',
    inHeader: false,
  },
  {
    id: 'inbox',
    name: 'Входящие',
    href: '/inbox',
    // Мобильного близнеца пока нет: экран читают за столом, разбирая день.
    hasMobile: false,
    hasMobileNested: false,
    inTabBar: null,
    // «Данные»: это вход в систему, а не её настройка.
    section: 'data',
    inHeader: false,
  },
  {
    id: 'quick-marks',
    name: 'Быстрые отметки',
    href: '/quick-marks',
    // Мобильный близнец есть: кнопку заводят там же, где по ней потом бьют, а
    // бьют по ней с телефона.
    hasMobile: true,
    hasMobileNested: false,
    // Под «More»: справочник настраивают раз в месяц, а таб-бар — для того,
    // что открывают каждый день.
    inTabBar: null,
    // «Настройка»: справочник кнопок настраивают раз в месяц.
    section: 'setup',
    inHeader: true,
  },
  {
    id: 'chat',
    name: 'Chat',
    href: '/chat',
    // Мобильный близнец `/m/chat` (`#118`): чат нужен там, где человек, а
    // человек — с телефоном.
    hasMobile: true,
    hasMobileNested: false,
    // Под «More»: пять слотов таб-бара заняты, а первый срез чата и живёт в
    // «More» по решению ADR-0017. Перестановка табов — отдельное решение при
    // слиянии personal-os, а не побочный эффект появления чата на телефоне.
    inTabBar: null,
    // «День»: с чатом разговаривают про сегодня.
    section: 'day',
    inHeader: false,
  },
  {
    id: 'daily-summary',
    name: 'Day summary',
    href: '/daily-summary',
    hasMobile: true,
    hasMobileNested: false,
    // First of the "More" screens: telling the app about your day is a daily
    // act, but the tab bar's five slots are already spoken for.
    inTabBar: null,
    // «День»: рассказать приложению про свой день — ежедневный акт.
    section: 'day',
    inHeader: false,
  },
  {
    id: 'table',
    name: 'Table',
    href: '/table',
    hasMobile: true,
    hasMobileNested: false,
    inTabBar: null,
    // «Данные»: таблица — это записи в другой развёртке.
    section: 'data',
    inHeader: false,
  },
  {
    id: 'categories',
    name: 'Categories',
    href: '/categories',
    hasMobile: true,
    hasMobileNested: true,
    inTabBar: 3,
    // «Настройка»: справочник категорий и полей.
    section: 'setup',
    inHeader: false,
  },
  {
    id: 'entries',
    name: 'Entries',
    href: '/entries',
    hasMobile: true,
    hasMobileNested: false,
    inTabBar: 1,
    // «Данные»: сами записи.
    section: 'data',
    inHeader: false,
  },
  {
    id: 'journal',
    name: 'Journal',
    href: '/journal',
    hasMobile: true,
    hasMobileNested: false,
    inTabBar: null,
    // «Данные»: журнал — записанное, перечитываемое позже.
    section: 'data',
    inHeader: false,
  },
  {
    id: 'insights',
    name: 'Insights',
    href: '/insights',
    hasMobile: true,
    hasMobileNested: false,
    inTabBar: null,
    // «Данные»: выводы, следующие из записей.
    section: 'data',
    inHeader: false,
  },
  {
    id: 'day-rules',
    name: 'Day rules',
    href: '/settings/day-rules',
    // Экран правил читают и правят с ноутбука: он про канон, а не про день, и
    // мобильного близнеца у него пока нет — мобильная оболочка открывает
    // десктопный маршрут, как это делали остальные экраны до своих срезов.
    hasMobile: false,
    hasMobileNested: false,
    // Под «More»: канон меняли дважды за месяц, а не дважды в день, и пять
    // слотов таб-бара заняты.
    inTabBar: null,
    // «Настройка»: канон дня.
    section: 'setup',
    inHeader: false,
  },
  {
    id: 'onboarding',
    name: 'Onboarding',
    href: '/onboarding',
    hasMobile: true,
    hasMobileNested: false,
    // Last of the "More" screens on purpose: setting categories up by talking
    // at the app is a rare act, not a daily one, and the tab bar's five slots
    // are already spoken for.
    inTabBar: null,
    // «Настройка»: разовая настройка категорий разговором.
    section: 'setup',
    inHeader: false,
  },
];

/**
 * Whether the screen's mobile version also serves the routes nested below it.
 *
 * `hasMobileNested` widens `hasMobile` and is meaningless without it, so the
 * conjunction is spelled once here: both the tab bar (which keeps a tab lit on
 * its detail screens) and `lib/view-mode` (which whitelists those detail routes)
 * ask the same question, and two copies of it drift into a tab that highlights a
 * route the router refuses to map.
 */
export function isNestedMobileRoute(route: AppRoute): boolean {
  return route.hasMobile && route.hasMobileNested;
}

/**
 * The `/m` twin of a screen's desktop href. The root `/` maps to the bare `/m`,
 * not `/m/`: a plain concat would leave a trailing slash that maps onto no
 * route. Only meaningful for a route whose `hasMobile` is true.
 */
export function mobileHref(route: AppRoute): string {
  return `${MOBILE_PATH_PREFIX}${route.href === '/' ? '' : route.href}`;
}

/** Tab-bar screens in tab order; the mobile-only "More" tab is appended by the bar itself. */
export const TAB_BAR_ROUTES: readonly AppRoute[] = APP_ROUTES.filter(
  (route) => route.inTabBar !== null
).sort((a, b) => (a.inTabBar ?? 0) - (b.inTabBar ?? 0));

/** Screens that did not fit in the tab bar and are reachable through "More". */
export const MORE_ROUTES: readonly AppRoute[] = APP_ROUTES.filter(
  (route) => route.inTabBar === null
);

/** One heading of the desktop drawer, with the screens filed under it. */
export interface NavSection {
  id: AppRouteSection;
  /** Heading text, in Russian — this list is read, not typed into. */
  name: string;
  /** Screens of the group, in registry order. */
  routes: readonly AppRoute[];
}

/**
 * The whole app as the desktop drawer prints it: three headings, every screen
 * under exactly one of them.
 *
 * Derived rather than written out, so a screen added to the registry appears in
 * the drawer by itself. Seventeen items in a single row do not fit any monitor
 * — the desktop container is capped at `max-w-7xl` regardless of screen width —
 * and an unsorted list of seventeen is not navigation either.
 */
export const NAV_SECTIONS: readonly NavSection[] = SECTION_ORDER.map((id) => ({
  id,
  name: SECTION_NAMES[id],
  routes: APP_ROUTES.filter((route) => route.section === id),
}));

/**
 * The screens the desktop header shows outside the drawer.
 *
 * Two of them, both daily: Today is the address the app opens on, and Быстрые
 * отметки is what a mark is made from. Everything else is one click away behind
 * the drawer button, which is the correct price for a screen opened weekly.
 */
export const HEADER_ROUTES: readonly AppRoute[] = APP_ROUTES.filter((route) => route.inHeader);

/**
 * Whether `pathname` is the screen `route` names, or one of its detail routes.
 *
 * Exact equality alone leaves `/day/2026-08-30`, `/week/2026-W35`,
 * `/categories/12` and `/roles/rules` with nothing marked at all, which is
 * exactly the state the old desktop row shipped in. `hasMobileNested` is the
 * registry's only record of "this screen owns the routes below it" — it is
 * named after the mobile twin because that is where the question first came up,
 * but the fact it states is about the screen, not about the shell.
 */
export function isActiveRoute(pathname: string, route: AppRoute): boolean {
  if (pathname === route.href) return true;
  return route.hasMobileNested && pathname.startsWith(`${route.href}/`);
}

/** One destination of the mobile tab bar. The id resolves to an icon in the UI layer. */
export interface MobileTab {
  id: string;
  name: string;
  href: string;
  /** True when the tab also covers the routes nested under `href`. */
  nested: boolean;
}

/**
 * Tab destinations: the registry's tab-bar screens, each pointing at its mobile
 * twin when it has one and at the desktop route otherwise (cramped but working
 * until its slice lands), plus the mobile-only "More" tab.
 */
export const MOBILE_TABS: readonly MobileTab[] = [
  ...TAB_BAR_ROUTES.map((route) => ({
    id: route.id,
    name: route.name,
    // A tab-bar screen without a mobile version yet points at its desktop route
    // (cramped but working); one with a mobile version points at its `/m` twin.
    href: route.hasMobile ? mobileHref(route) : route.href,
    nested: isNestedMobileRoute(route),
  })),
  { id: MORE_ROUTE_ID, name: 'More', href: MORE_PATH, nested: false },
];

/**
 * Deep link that opens an Entries screen with its editor already up.
 *
 * Both Entries screens read it and both shells link to it, so the literal lives
 * here rather than in any one of them: a rename in four unconnected places is a
 * dead "+" button on whichever shell was missed.
 */
export const NEW_ENTRY_PARAM = 'new';
export const NEW_ENTRY_VALUE = '1';
export const NEW_ENTRY_QUERY = `?${NEW_ENTRY_PARAM}=${NEW_ENTRY_VALUE}`;

/** Whether a screen's query string asks for the editor to open on mount. */
export function wantsNewEntry(params: { get(name: string): string | null }): boolean {
  return params.get(NEW_ENTRY_PARAM) === NEW_ENTRY_VALUE;
}

/** Header text of the mobile shell when the route is not a known screen. */
export const DEFAULT_SCREEN_TITLE = 'Habit Tracker';

/**
 * Header text for a mobile route: the tab it belongs to, else the app name.
 *
 * A tab that owns its nested routes keeps naming the header on them, so
 * `/m/categories/12` reads "Categories" instead of dropping to the app name the
 * moment the user opens a detail screen.
 */
export function mobileScreenTitle(pathname: string): string {
  const tab =
    MOBILE_TABS.find((candidate) => candidate.href === pathname) ??
    MOBILE_TABS.find(
      (candidate) => candidate.nested && pathname.startsWith(`${candidate.href}/`)
    );
  if (tab) return tab.name;
  // A mobile screen reachable only through "More" (Journal) has no tab, so its
  // header would otherwise drop to the app name. Name it from the registry.
  const screen = APP_ROUTES.find((route) => route.hasMobile && mobileHref(route) === pathname);
  return screen?.name ?? DEFAULT_SCREEN_TITLE;
}
