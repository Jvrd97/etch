---
name: fixed-overlays-inside-animate-fade-rise
description: Ловушка вёрстки — position:fixed внутри колонки .animate-fade-rise привязывается к колонке, а не к экрану; листы и диалоги Today выносятся из неё
metadata:
  type: project
---

`.animate-fade-rise` в `app/globals.css` идёт с `both`, и после анимации у колонки остаётся `transform: translateY(0)`. Transform делает колонку containing block для `position: fixed` потомков и отдельным stacking context.

**Why:** до #206 страницы Today (`app/today/page.tsx`, `app/m/today/page.tsx`) держали `FullScreenSheet`, диалог списка, `VoiceDaySheet` и `EntryEditorSheet` внутри такой колонки. На телефоне «полноэкранный» лист был высотой с колонку, а sticky-шапка и таб-бар (z-40) рисовались поверх него. На десктопе диалог центрировался в колонке и затемнял только её.

**How to apply:** новый лист, модалка или диалог на странице с корнем `animate-fade-rise` — соседний узел колонки (фрагмент `<> <div class="…animate-fade-rise">…</div> {overlays} </>`), а не её потомок. Проверка вживую: высота листа равна высоте экрана, шапка и таб-бар под ним.
