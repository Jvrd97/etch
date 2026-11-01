---
name: project-cache-first-direction
description: Owner direction (2026-11-01) for iOS — screens open from cached snapshot instantly, taps show at once, server work goes to background; server is reached over Tailscale (hundreds of ms per request)
metadata:
  type: project
---

Владелец (2026-11-01): «Frontend не должен ждать backend. Нажал — сразу отобразилось. Экраны горячие, их кэш открывается сразу».

**Why:** приложение ходит на сервер по Tailscale, каждый запрос — сотни мс; любое ожидание сети до первого кадра или до отклика на нажатие видно человеку.

**How to apply:** новый экран или запись проектируй как «снимок из кэша сразу, сеть фоном» и «запись через outbox с немедленным показом». На 2026-11-01 `ReadThroughCache` был network-first (кэш только при обрыве сети), а outbox показывал записи сразу только офлайн — проверь, не поменялось ли это. Открытые развилки владельца: срок жизни снимка, шифрование кэша, какие записи можно делать оптимистично, интервал повторного чтения при смене вкладки.
