// [review:need-review] PHASE-03/109
// summary: unit tests for the login route helpers — open-redirect refusal on `next`, no redirect loop on the login page itself

import { describe, expect, it } from 'bun:test';
import {
  DEFAULT_AFTER_LOGIN,
  LOGIN_PATH,
  NEXT_PARAM,
  afterLoginHref,
  isLoginPath,
  isSafeReturnPath,
  loginHref,
  loginRedirectTarget,
  shouldRedirectToLogin,
} from './auth';

describe('isLoginPath', () => {
  it('recognises the login screen and nothing else', () => {
    expect(isLoginPath(LOGIN_PATH)).toBe(true);
    expect(isLoginPath('/login/extra')).toBe(false);
    expect(isLoginPath('/day/2026-08-30')).toBe(false);
  });
});

describe('isSafeReturnPath', () => {
  it('accepts a path inside the app', () => {
    expect(isSafeReturnPath('/goals')).toBe(true);
    expect(isSafeReturnPath('/m/today')).toBe(true);
  });

  it('refuses anything that can leave the origin', () => {
    // `//host` is a protocol-relative absolute URL: a leading-slash test alone
    // would send a reader who just typed the key to another site.
    expect(isSafeReturnPath('//evil.example')).toBe(false);
    expect(isSafeReturnPath('/\\evil.example')).toBe(false);
    expect(isSafeReturnPath('https://evil.example')).toBe(false);
    expect(isSafeReturnPath('goals')).toBe(false);
  });
});

describe('loginHref', () => {
  it('remembers where the reader was going', () => {
    expect(loginHref('/day/2026-08-30')).toBe(
      `${LOGIN_PATH}?${NEXT_PARAM}=${encodeURIComponent('/day/2026-08-30')}`
    );
  });

  it('drops a target that could leave the origin', () => {
    expect(loginHref('//evil.example')).toBe(LOGIN_PATH);
  });

  it('does not remember the login screen itself', () => {
    expect(loginHref(LOGIN_PATH)).toBe(LOGIN_PATH);
  });
});

describe('afterLoginHref', () => {
  it('returns to the remembered screen', () => {
    expect(afterLoginHref('/goals')).toBe('/goals');
  });

  it('falls back to the dashboard when there is nothing to return to', () => {
    expect(afterLoginHref(null)).toBe(DEFAULT_AFTER_LOGIN);
  });

  it('refuses a foreign target', () => {
    expect(afterLoginHref('https://evil.example')).toBe(DEFAULT_AFTER_LOGIN);
    expect(afterLoginHref('//evil.example')).toBe(DEFAULT_AFTER_LOGIN);
  });

  it('never bounces back to the login screen', () => {
    expect(afterLoginHref(LOGIN_PATH)).toBe(DEFAULT_AFTER_LOGIN);
  });
});

describe('shouldRedirectToLogin', () => {
  it('sends an unauthenticated screen to the login page', () => {
    expect(shouldRedirectToLogin(401, '/entries')).toBe(true);
  });

  it('leaves the login page alone — there a 401 means "wrong key"', () => {
    expect(shouldRedirectToLogin(401, LOGIN_PATH)).toBe(false);
  });

  it('ignores every other failure', () => {
    expect(shouldRedirectToLogin(403, '/entries')).toBe(false);
    expect(shouldRedirectToLogin(500, '/entries')).toBe(false);
    expect(shouldRedirectToLogin(200, '/entries')).toBe(false);
  });
});

describe('loginRedirectTarget', () => {
  it('carries the query string across, so the reader lands where they were going', () => {
    expect(loginRedirectTarget(401, '/entries', '?new=1')).toBe(
      `${LOGIN_PATH}?${NEXT_PARAM}=${encodeURIComponent('/entries?new=1')}`
    );
  });

  it('is null when nothing should move', () => {
    expect(loginRedirectTarget(200, '/entries')).toBeNull();
    expect(loginRedirectTarget(500, '/entries')).toBeNull();
    expect(loginRedirectTarget(401, LOGIN_PATH)).toBeNull();
  });
});
