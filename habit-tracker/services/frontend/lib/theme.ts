// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: theme tokens that have to exist outside CSS (manifest + viewport meta)

/**
 * App shell background / theme colour. Kept in sync by hand with
 * `--color-background` in `app/globals.css`: the manifest and the `theme-color`
 * meta tag are read by the OS, which never sees the stylesheet.
 */
export const THEME_COLOR = '#090909';
