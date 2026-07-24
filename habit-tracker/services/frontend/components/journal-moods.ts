// [review:need-review] PHASE-01/44-mobile-journal
// summary: the journal mood registry (value, label, icon, colour) shared by the desktop /journal page and the mobile /m/journal screen so a mood renders identically in both shells

import { CloudRain, Frown, Meh, Smile, Wind, Zap, type LucideIcon } from 'lucide-react';

/** One selectable mood: its stored value plus how it renders. */
export interface MoodOption {
  /** Value persisted on the entry (`JournalEntry.mood`). */
  value: string;
  /** Human label shown in the picker and read out to assistive tech. */
  label: string;
  icon: LucideIcon;
  /** Tailwind text-colour class for the icon. */
  color: string;
}

/**
 * The moods a journal entry may carry.
 *
 * Shared rather than copied into each shell: the desktop page and the mobile
 * screen both draw the picker and both look a mood up to badge an entry, and two
 * private copies drift into an icon that means one thing on desktop and another
 * on mobile the first time the list changes.
 */
export const MOOD_OPTIONS: readonly MoodOption[] = [
  { value: 'happy', label: 'Happy', icon: Smile, color: 'text-warning' },
  { value: 'sad', label: 'Sad', icon: Frown, color: 'text-info' },
  { value: 'neutral', label: 'Neutral', icon: Meh, color: 'text-text-secondary' },
  { value: 'excited', label: 'Excited', icon: Zap, color: 'text-lime' },
  { value: 'anxious', label: 'Anxious', icon: CloudRain, color: 'text-danger' },
  { value: 'calm', label: 'Calm', icon: Wind, color: 'text-green-secondary' },
];

/** The mood option behind a stored value, or undefined when it is empty or unknown. */
export function moodOption(mood: string | undefined): MoodOption | undefined {
  return MOOD_OPTIONS.find((option) => option.value === mood);
}
