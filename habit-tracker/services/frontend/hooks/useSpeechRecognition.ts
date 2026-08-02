'use client';
// [review:need-review] PHASE-01/84-voice-day-input
// summary: dictation over the Web Speech API — a continuous ru-RU session that streams finished phrases to a callback and keeps the forming one local, degrading to `supported: false` where the API is absent

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';

/**
 * The dictation language.
 *
 * Fixed rather than derived from the browser: the thing being dictated is a
 * Russian retelling of a day, and a phone set to English would otherwise
 * transcribe "съел борщ" into whatever English words it sounds closest to.
 */
export const DICTATION_LANG = 'ru-RU';

/** Shown when the browser refuses the microphone or the engine gives up. */
export const DICTATION_ERROR = 'Не удалось расслышать — проверьте доступ к микрофону';

/**
 * Engine outcomes that are not failures.
 *
 * `no-speech` fires whenever the sheet is opened and the user thinks for a
 * moment before speaking, and `aborted` is what `stop()` and unmounting look
 * like from inside. Both would otherwise raise a banner for something the user
 * did on purpose, which is how a banner stops being read.
 */
const SILENT_ERRORS = new Set(['no-speech', 'aborted']);

/**
 * The slice of the Web Speech API this hook drives.
 *
 * Declared here because the DOM lib does not carry it: the API is not on a
 * standards track and ships prefixed in Safari. Narrow on purpose — the fields
 * below are the ones actually touched, so anything else the browser offers
 * cannot be reached by accident.
 */
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionResultEventLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
}

interface SpeechRecognitionAlternativeLike {
  transcript: string;
}

interface SpeechRecognitionResultLike extends ArrayLike<SpeechRecognitionAlternativeLike> {
  isFinal: boolean;
}

interface SpeechRecognitionResultEventLike {
  /** Index of the first result of this event; earlier ones were delivered already. */
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

type SpeechCapableWindow = typeof globalThis & {
  SpeechRecognition?: SpeechRecognitionConstructor;
  webkitSpeechRecognition?: SpeechRecognitionConstructor;
};

/**
 * Subscription for a capability that cannot change while the page is open.
 *
 * `useSyncExternalStore` wants one, and there is genuinely nothing to listen
 * to: a browser does not grow speech recognition mid-session.
 */
function subscribeToNothing(): () => void {
  return () => {};
}

/** The constructor this browser offers, under either name, or null. */
function recognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof globalThis === 'undefined') return null;
  const speechWindow = globalThis as SpeechCapableWindow;
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition ?? null;
}

export interface UseSpeechRecognitionOptions {
  /**
   * Called with each phrase the engine has finished, never with a forming one.
   *
   * The hook accumulates nothing: a dictated day is edited by hand afterwards,
   * so the text has to live in the field the user is editing, not in a second
   * copy here that would silently win the next time a phrase lands.
   */
  onResult: (text: string) => void;
}

export interface UseSpeechRecognitionResult {
  /** Whether this browser can listen at all. False leaves the screen typing-only. */
  supported: boolean;
  listening: boolean;
  /** The phrase currently being recognised. Display only — it is not final. */
  interim: string;
  /** The last real failure, or null. A silence is not a failure. */
  error: string | null;
  /** Begin a session. A no-op when unsupported or already listening. */
  start: () => void;
  /** End the session. Whatever was final has already been delivered. */
  stop: () => void;
}

/**
 * Dictation as a hook: press start, get finished phrases, press stop.
 *
 * The engine is a long-lived mutable object with three callbacks, which is the
 * opposite of how a component wants to read state, so everything crossing that
 * boundary is pinned by a ref and everything the UI renders is state. In
 * particular `onResult` is read through a ref: the caller passes a closure over
 * the text being edited, so it is a new function on every keystroke, and
 * rebuilding the session for that would cut the user off mid-sentence.
 */
export function useSpeechRecognition({
  onResult,
}: UseSpeechRecognitionOptions): UseSpeechRecognitionResult {
  // Read through `useSyncExternalStore` rather than in an effect: the server
  // has no `SpeechRecognition` and must render the typing-only screen, and this
  // is the API that lets the two renders disagree on purpose instead of
  // hydrating one thing and then flipping it.
  const supported = useSyncExternalStore(
    subscribeToNothing,
    () => recognitionConstructor() !== null,
    () => false
  );
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState('');
  const [error, setError] = useState<string | null>(null);

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const onResultRef = useRef(onResult);

  // Synced in an effect rather than during render: a ref written while
  // rendering is a value the renderer is free to discard, and every phrase
  // arrives from a browser event long after the commit anyway.
  useEffect(() => {
    onResultRef.current = onResult;
  });

  // A microphone left open behind a closed sheet is the one failure here the
  // user would see in the status bar and never connect back to this app.
  // `abort` rather than `stop`: the session is being discarded, not finished.
  useEffect(() => {
    return () => {
      recognitionRef.current?.abort();
      recognitionRef.current = null;
    };
  }, []);

  const start = useCallback(() => {
    if (recognitionRef.current !== null) return;
    const Recognition = recognitionConstructor();
    if (Recognition === null) return;

    const recognition = new Recognition();
    recognition.lang = DICTATION_LANG;
    // A day is several sentences with thinking pauses between them. A
    // non-continuous session ends at the first pause and drops the rest.
    recognition.continuous = true;
    recognition.interimResults = true;

    recognition.onresult = (event) => {
      let finalText = '';
      let formingText = '';
      // From `resultIndex` on: everything before it was delivered by an
      // earlier event, and re-reading it would append the day twice.
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const text = result[0]?.transcript ?? '';
        if (result.isFinal) finalText += text;
        else formingText += text;
      }
      setInterim(formingText);
      if (finalText.length > 0) onResultRef.current(finalText);
    };

    recognition.onerror = (event) => {
      if (!SILENT_ERRORS.has(event.error)) setError(DICTATION_ERROR);
      setListening(false);
      setInterim('');
    };

    recognition.onend = () => {
      setListening(false);
      setInterim('');
      recognitionRef.current = null;
    };

    recognitionRef.current = recognition;
    setError(null);
    setInterim('');
    setListening(true);
    recognition.start();
  }, []);

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
    // `onend` clears the rest; setting it here too covers an engine that
    // never fires it, which leaves a button stuck reading "Стоп".
    setListening(false);
    setInterim('');
  }, []);

  return { supported, listening, interim, error, start, stop };
}
