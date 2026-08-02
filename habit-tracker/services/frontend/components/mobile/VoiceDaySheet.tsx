'use client';
// [review:need-review] PHASE-01/84-voice-day-input
// summary: the dictation sheet of /m/today — speak the day, watch it land in an editable field, parse it into a plan and write the checked half, all under one bar action that carries both steps

import { useCallback, useEffect, useRef } from 'react';
import { Mic, Square } from 'lucide-react';
import LoadingSpinner from '@/components/LoadingSpinner';
import DayPlanPreview, {
  EMPTY_PLAN_MESSAGE,
  planIsEmpty,
} from '@/components/mobile/DayPlanPreview';
import FullScreenSheet from '@/components/mobile/FullScreenSheet';
import { useDailySummary } from '@/hooks/useDailySummary';
import { useSpeechRecognition } from '@/hooks/useSpeechRecognition';
import { TAP_TARGET_PX, entryInputClass } from '@/lib/ui-constants';

/** Accessible name of the sheet, and its bar title. */
export const VOICE_SHEET_TITLE = 'Рассказать день';

/** Accessible name of the text the dictation fills in and the user may fix. */
export const DICTATION_FIELD_LABEL = 'Что было за день';

/** Bar action of the first step: hand the text to the model. */
export const PARSE_LABEL = 'Разобрать день';

/** In-content action that re-parses text edited after a plan was built. */
export const REPARSE_LABEL = 'Пересобрать план';

export const START_DICTATION_LABEL = 'Начать диктовку';
export const STOP_DICTATION_LABEL = 'Остановить диктовку';

/** Shown instead of the microphone where the browser cannot listen. */
export const UNSUPPORTED_HINT =
  'Этот браузер не умеет распознавать речь — расскажите день текстом или продиктуйте его кнопкой микрофона на клавиатуре.';

const PRIMARY_BUTTON_CLASS =
  'w-full inline-flex items-center justify-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-transform duration-200 active:scale-95 disabled:opacity-40 disabled:active:scale-100';

const SECONDARY_BUTTON_CLASS =
  'w-full inline-flex items-center justify-center gap-2 px-5 py-3 bg-surface border border-white/10 text-text-primary rounded-3xl font-medium transition-transform duration-200 active:scale-95 disabled:opacity-40';

export interface VoiceDaySheetProps {
  /** Dismiss without writing anything. */
  onClose: () => void;
  /** The day went in: the screen underneath reloads and drops the sheet. */
  onApplied: () => void;
}

/**
 * Speak a day, check what it would write, write it.
 *
 * The sheet exists because the two things a tracker asks for every evening —
 * "how many" and "what did you eat" — are the two things nobody wants to type
 * on a phone. Speaking them takes seconds, and the backend already turns the
 * text into a reviewable plan, so all this adds is the microphone and the
 * review in one place the user was already standing in.
 *
 * Both steps live under the single bar action, which changes its name as the
 * step changes: parsing first, writing once there is something to write. A
 * second control for the second step would put the day's most consequential
 * button somewhere the thumb has to go looking for it.
 *
 * Recognised speech is appended to a plain textarea rather than held anywhere
 * of its own. Recognition mishears — reliably, on exactly the words a food
 * diary is made of — and a transcript the user cannot correct is a day they
 * abandon instead of fixing.
 */
export default function VoiceDaySheet({ onClose, onApplied }: VoiceDaySheetProps) {
  const day = useDailySummary({ onApplied });

  // The append target read through a ref: `setTranscript` is a plain state
  // setter, so appending needs the current text, and closing over it would
  // hand the recogniser a value from whichever render installed the handler.
  // Synced in an effect, not during render — a ref written while rendering is
  // a value the renderer may discard, and speech arrives after the commit.
  const transcriptRef = useRef(day.transcript);
  useEffect(() => {
    transcriptRef.current = day.transcript;
  });

  const setTranscript = day.setTranscript;
  const appendPhrase = useCallback(
    (phrase: string) => {
      const existing = transcriptRef.current.trimEnd();
      setTranscript(existing.length > 0 ? `${existing} ${phrase}` : phrase);
    },
    [setTranscript]
  );

  const speech = useSpeechRecognition({ onResult: appendPhrase });

  // A plan with nothing in it is not a step forward: the bar keeps offering to
  // parse, because saying more is the only thing that helps.
  const hasPlan = day.draft.status === 'done' && !planIsEmpty(day);
  const applying = day.applyState.status === 'applying';

  const parse = useCallback(() => {
    // Parsing mid-sentence would send half a day. Stopping first also delivers
    // whatever the engine had already finalised.
    speech.stop();
    void day.generate();
  }, [speech, day]);

  const doneLabel = hasPlan ? `Записать (${day.enabledCount})` : PARSE_LABEL;
  const doneDisabled = hasPlan
    ? !day.canApply
    : !day.canGenerate && day.transcript.trim().length === 0;

  const error =
    day.draft.status === 'error'
      ? day.draft.message
      : day.applyState.status === 'error'
        ? day.applyState.message
        : speech.error;

  return (
    <FullScreenSheet
      title={VOICE_SHEET_TITLE}
      onCancel={onClose}
      onDone={hasPlan ? () => void day.apply() : parse}
      busy={applying}
      doneLabel={doneLabel}
      doneDisabled={doneDisabled}
      error={error}
    >
      {speech.supported ? (
        <button
          type="button"
          onClick={speech.listening ? speech.stop : speech.start}
          aria-label={speech.listening ? STOP_DICTATION_LABEL : START_DICTATION_LABEL}
          style={{ minHeight: TAP_TARGET_PX }}
          className={speech.listening ? SECONDARY_BUTTON_CLASS : PRIMARY_BUTTON_CLASS}
        >
          {speech.listening ? (
            <>
              <Square className="w-4 h-4 shrink-0 fill-current" strokeWidth={2} />
              Слушаю — остановить
            </>
          ) : (
            <>
              <Mic className="w-4 h-4 shrink-0" strokeWidth={2} />
              Говорить
            </>
          )}
        </button>
      ) : (
        <p className="text-[13px] text-text-secondary">{UNSUPPORTED_HINT}</p>
      )}

      <textarea
        value={day.transcript}
        onChange={(e) => day.setTranscript(e.target.value)}
        rows={5}
        aria-label={DICTATION_FIELD_LABEL}
        placeholder="Например: съел борщ и котлету, отжался 30 раз"
        className={`${entryInputClass} resize-y`}
      />

      {/* The phrase still forming, shown apart from the field: the engine
          rewrites it word by word, and letting it into the textarea would move
          the caret under a user who is editing the sentence above it. */}
      {speech.interim.length > 0 && (
        <p className="text-[13px] text-text-disabled break-words">{speech.interim}</p>
      )}

      {day.draft.status === 'loading' && <LoadingSpinner size="lg" />}

      {day.draft.status === 'done' &&
        (planIsEmpty(day) ? (
          <p className="text-sm text-text-secondary">{EMPTY_PLAN_MESSAGE}</p>
        ) : (
          <div className="space-y-3">
            <DayPlanPreview day={day} />

            {/* The plan is built from the text above, which is still editable —
                so there has to be a way to rebuild it. It is a secondary
                control because the common path is to write what was parsed;
                correcting a misheard word and re-parsing is the exception. */}
            <button
              type="button"
              onClick={parse}
              disabled={!day.canGenerate}
              style={{ minHeight: TAP_TARGET_PX }}
              className={SECONDARY_BUTTON_CLASS}
            >
              {REPARSE_LABEL}
            </button>
          </div>
        ))}
    </FullScreenSheet>
  );
}
