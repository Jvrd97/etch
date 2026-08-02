// [review:need-review] PHASE-01/84-voice-day-input
// summary: tests for useSpeechRecognition — absent API degrades instead of throwing, final results stream out while interim text stays local, the callback is read through a ref so a re-render never restarts the session, and stop/unmount leave nothing listening

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook } from '@testing-library/react';
import { useSpeechRecognition } from '@/hooks/useSpeechRecognition';

/**
 * The half of the Web Speech API this hook touches, driveable from a test.
 *
 * Nothing fakes the recognition itself — the browser's engine is not the unit
 * here. What is under test is the wiring around it: which handler is attached,
 * what a final result does that an interim one must not, and what is left
 * running after `stop`.
 */
class FakeRecognition {
  static instances: FakeRecognition[] = [];

  lang = '';
  continuous = false;
  interimResults = false;
  started = 0;
  stopped = 0;
  aborted = 0;

  onresult: ((event: SpeechRecognitionEventLike) => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;

  constructor() {
    FakeRecognition.instances.push(this);
  }

  start(): void {
    this.started += 1;
  }

  stop(): void {
    this.stopped += 1;
    this.onend?.();
  }

  abort(): void {
    this.aborted += 1;
  }

  /** Deliver one recognition result, final or still forming. */
  emit(transcript: string, isFinal: boolean): void {
    this.onresult?.({
      resultIndex: 0,
      results: [{ isFinal, 0: { transcript }, length: 1 }],
    });
  }
}

interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string }; length: number }>;
}

type SpeechWindow = typeof globalThis & {
  SpeechRecognition?: unknown;
  webkitSpeechRecognition?: unknown;
};

function installFake(): void {
  FakeRecognition.instances = [];
  (globalThis as SpeechWindow).SpeechRecognition = FakeRecognition;
}

function uninstall(): void {
  delete (globalThis as SpeechWindow).SpeechRecognition;
  delete (globalThis as SpeechWindow).webkitSpeechRecognition;
}

/** The instance the hook is driving, or a failure that says so. */
function current(): FakeRecognition {
  const instance = FakeRecognition.instances.at(-1);
  if (!instance) throw new Error('the hook never constructed a recogniser');
  return instance;
}

afterEach(() => {
  cleanup();
  uninstall();
});

describe('useSpeechRecognition without the API', () => {
  it('reports itself unsupported instead of pretending', () => {
    const { result } = renderHook(() => useSpeechRecognition({ onResult: mock() }));

    expect(result.current.supported).toBe(false);
  });

  it('survives a start on a browser that cannot listen', () => {
    // Firefox and older Safari land here. The screen still has a textarea, so
    // the honest outcome is a button that does nothing, not a crashed page.
    const onResult = mock();
    const { result } = renderHook(() => useSpeechRecognition({ onResult }));

    act(() => result.current.start());

    expect(result.current.listening).toBe(false);
    expect(onResult).not.toHaveBeenCalled();
  });
});

describe('useSpeechRecognition with the API', () => {
  it('dictates in Russian, continuously, showing the phrase as it forms', () => {
    installFake();
    const { result } = renderHook(() => useSpeechRecognition({ onResult: mock() }));

    act(() => result.current.start());

    // A day is several sentences with pauses in them: a session that ends at
    // the first pause would drop everything after "так, что ещё".
    expect(current().continuous).toBe(true);
    expect(current().interimResults).toBe(true);
    expect(current().lang).toBe('ru-RU');
    expect(result.current.listening).toBe(true);
  });

  it('hands out a phrase only once it is final', () => {
    installFake();
    const onResult = mock();
    const { result } = renderHook(() => useSpeechRecognition({ onResult }));
    act(() => result.current.start());

    act(() => current().emit('съел борщ', false));

    // Interim text is shown, never appended: the engine rewrites it freely,
    // and appending every revision spells the sentence three times over.
    expect(result.current.interim).toBe('съел борщ');
    expect(onResult).not.toHaveBeenCalled();

    act(() => current().emit('съел борщ и котлету', true));

    expect(onResult).toHaveBeenCalledTimes(1);
    expect(onResult).toHaveBeenCalledWith('съел борщ и котлету');
    expect(result.current.interim).toBe('');
  });

  it('keeps listening through a re-render with a fresh callback', () => {
    // The sheet passes a closure over the day's text, so `onResult` is a new
    // function on every keystroke. Restarting the engine for that would cut
    // the user off mid-sentence.
    installFake();
    const first = mock();
    const second = mock();
    const { result, rerender } = renderHook(
      ({ onResult }: { onResult: (text: string) => void }) =>
        useSpeechRecognition({ onResult }),
      { initialProps: { onResult: first } }
    );
    act(() => result.current.start());

    rerender({ onResult: second });
    act(() => current().emit('пробежал 5 километров', true));

    expect(FakeRecognition.instances).toHaveLength(1);
    expect(current().started).toBe(1);
    expect(second).toHaveBeenCalledWith('пробежал 5 километров');
    expect(first).not.toHaveBeenCalled();
  });

  it('stops listening when told to', () => {
    installFake();
    const { result } = renderHook(() => useSpeechRecognition({ onResult: mock() }));
    act(() => result.current.start());

    act(() => result.current.stop());

    expect(current().stopped).toBe(1);
    expect(result.current.listening).toBe(false);
  });

  it('drops the session when the screen goes away', () => {
    // A microphone left open behind a closed sheet is the one bug in this hook
    // the user would notice in the status bar and never connect to the app.
    installFake();
    const { result, unmount } = renderHook(() =>
      useSpeechRecognition({ onResult: mock() })
    );
    act(() => result.current.start());

    unmount();

    expect(current().aborted).toBe(1);
  });

  it('surfaces a refused microphone as an error', () => {
    installFake();
    const { result } = renderHook(() => useSpeechRecognition({ onResult: mock() }));
    act(() => result.current.start());

    act(() => current().onerror?.({ error: 'not-allowed' }));

    expect(result.current.error).not.toBeNull();
    expect(result.current.listening).toBe(false);
  });

  it('treats a silence as a silence, not a failure', () => {
    // `no-speech` fires whenever someone opens the sheet and thinks for a
    // moment. Showing it as an error trains the user to ignore the banner.
    installFake();
    const { result } = renderHook(() => useSpeechRecognition({ onResult: mock() }));
    act(() => result.current.start());

    act(() => current().onerror?.({ error: 'no-speech' }));

    expect(result.current.error).toBeNull();
  });

  it('follows the engine when it stops on its own', () => {
    installFake();
    const { result } = renderHook(() => useSpeechRecognition({ onResult: mock() }));
    act(() => result.current.start());

    act(() => current().onend?.());

    expect(result.current.listening).toBe(false);
  });
});
