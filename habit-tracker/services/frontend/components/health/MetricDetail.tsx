"use client";
// [review:need-review] PHASE-02/68
// summary: the metric detail body both /health/[identifier] and /m/health/[identifier] render — the daily series of a switchable period, the chosen day, and its 24 hours (empty hours drawn as "нет данных", min–max for a discrete hour); sleep shows its nights instead of hours

import Link from "next/link";
import { useState } from "react";
import type { HealthMetricDays, HealthMetricHours } from "@/lib/api";
import {
  DEFAULT_PERIOD_DAYS,
  HEALTH_PERIODS,
  formatValue,
  hourLabel,
  hourRange,
  hourSlots,
} from "@/lib/health";
import SleepSection, { nightLabel } from "./SleepSection";
import {
  useMetricDays,
  useMetricHours,
  type DaysRead,
  type HoursRead,
} from "./useMetricDetail";
import { useSleepNights, type SleepRead } from "./useSleepNights";

export interface MetricDetailProps {
  identifier: string;
  backHref: string;
  readDays?: DaysRead;
  readHours?: HoursRead;
  readNights?: SleepRead;
}

export const DETAIL_ERROR_TEXT = "Не удалось загрузить метрику";
export const DETAIL_EMPTY_TEXT = "Данных по метрике нет за выбранный период.";

export default function MetricDetail({
  identifier,
  backHref,
  readDays,
  readHours,
  readNights,
}: MetricDetailProps) {
  const [periodDays, setPeriodDays] = useState(DEFAULT_PERIOD_DAYS);
  const [pickedDay, setPickedDay] = useState<string | null>(null);
  const series = useMetricDays(identifier, periodDays, readDays);

  return (
    <div className="space-y-5 animate-fade-rise">
      <Link
        href={backHref}
        className="inline-flex min-h-11 items-center text-sm font-medium text-lime"
      >
        ← Все метрики
      </Link>
      {series.status === "loading" && (
        <p role="status" className="text-sm text-text-secondary">
          Загрузка…
        </p>
      )}
      {series.status === "error" && (
        <p role="alert" className="text-sm text-danger">
          {DETAIL_ERROR_TEXT}
        </p>
      )}
      {series.status === "ready" && (
        <Loaded
          series={series.data}
          periodDays={periodDays}
          onPeriod={setPeriodDays}
          pickedDay={pickedDay}
          onDay={setPickedDay}
          readHours={readHours}
          readNights={readNights}
        />
      )}
    </div>
  );
}

interface LoadedProps {
  series: HealthMetricDays;
  periodDays: number;
  onPeriod: (days: number) => void;
  pickedDay: string | null;
  onDay: (day: string) => void;
  readHours?: HoursRead;
  readNights?: SleepRead;
}

function Loaded({
  series,
  periodDays,
  onPeriod,
  pickedDay,
  onDay,
  readHours,
  readNights,
}: LoadedProps) {
  const isSleep = series.kind === "sleep";
  const latest = series.days.at(-1)?.date ?? null;
  // The picked day only counts while it is still inside the series; a shorter period drops it.
  const picked = series.days.some((day) => day.date === pickedDay)
    ? pickedDay
    : null;
  const day = picked ?? latest;

  return (
    <>
      <h1 className="text-2xl font-semibold text-text-primary">
        {series.display_name}
      </h1>
      <PeriodSwitch periodDays={periodDays} onPeriod={onPeriod} />
      {series.days.length === 0 ? (
        <p role="status" className="text-sm text-text-secondary">
          {DETAIL_EMPTY_TEXT}
        </p>
      ) : (
        <>
          <DailyList series={series} day={day} onDay={onDay} />
          {isSleep ? (
            <Nights read={readNights} />
          ) : (
            day !== null && (
              <Hours
                identifier={series.identifier}
                day={day}
                read={readHours}
              />
            )
          )}
        </>
      )}
    </>
  );
}

function PeriodSwitch({
  periodDays,
  onPeriod,
}: {
  periodDays: number;
  onPeriod: (days: number) => void;
}) {
  return (
    <div role="group" aria-label="Период" className="flex gap-2">
      {HEALTH_PERIODS.map((period) => (
        <button
          key={period.days}
          type="button"
          aria-pressed={period.days === periodDays}
          onClick={() => onPeriod(period.days)}
          className={`min-h-11 rounded-full px-4 text-sm ${
            period.days === periodDays
              ? "bg-lime text-black"
              : "bg-card text-text-secondary"
          }`}
        >
          {period.label}
        </button>
      ))}
    </div>
  );
}

function DailyList({
  series,
  day,
  onDay,
}: {
  series: HealthMetricDays;
  day: string | null;
  onDay: (day: string) => void;
}) {
  return (
    <section aria-labelledby="health-days" className="space-y-2">
      <h2
        id="health-days"
        className="text-sm font-semibold text-text-secondary"
      >
        По дням
      </h2>
      <ol className="overflow-hidden rounded-3xl border border-white/5 bg-card">
        {[...series.days].reverse().map((entry) => (
          <li
            key={entry.date}
            className="border-b border-white/5 last:border-b-0"
          >
            <button
              type="button"
              aria-pressed={entry.date === day}
              onClick={() => onDay(entry.date)}
              className={`flex min-h-11 w-full items-center justify-between gap-4 px-4 py-2 text-sm ${
                entry.date === day ? "bg-white/5" : ""
              }`}
            >
              <span className="text-text-secondary">
                {nightLabel(entry.date)}
              </span>
              <span className="tabular-nums text-text-primary">
                {formatValue(entry.value)} {series.canonical_unit}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Hours({
  identifier,
  day,
  read,
}: {
  identifier: string;
  day: string;
  read?: HoursRead;
}) {
  const state = useMetricHours(identifier, day, true, read);
  return (
    <section aria-labelledby="health-hours" className="space-y-2">
      <h2
        id="health-hours"
        className="text-sm font-semibold text-text-secondary"
      >
        Часы: {nightLabel(day)}
      </h2>
      {state.status === "loading" && (
        <p role="status" className="text-sm text-text-secondary">
          Загрузка…
        </p>
      )}
      {state.status === "error" && (
        <p role="alert" className="text-sm text-danger">
          {DETAIL_ERROR_TEXT}
        </p>
      )}
      {state.status === "ready" && <HourRows hours={state.data} />}
    </section>
  );
}

function HourRows({ hours }: { hours: HealthMetricHours }) {
  const slots = hourSlots(hours.hours);
  const peak = Math.max(0, ...hours.hours.map((hour) => hour.value));
  return (
    <ol
      aria-label="Часы дня"
      className="overflow-hidden rounded-3xl border border-white/5 bg-card"
    >
      {slots.map((slot, hour) => (
        <li
          key={hour}
          className="flex min-h-9 items-center gap-3 border-b border-white/5 px-4 py-1 text-sm last:border-b-0"
        >
          <span className="w-12 tabular-nums text-text-secondary">
            {hourLabel(hour)}
          </span>
          {slot === null ? (
            <span className="text-text-secondary">нет данных</span>
          ) : (
            <>
              <span
                aria-hidden="true"
                className="h-2 rounded-full bg-lime"
                style={{
                  width: `${peak > 0 ? Math.max(2, (slot.value / peak) * 40) : 2}%`,
                }}
              />
              <span className="ml-auto tabular-nums text-text-primary">
                {formatValue(slot.value)}
              </span>
              {hours.kind === "discrete" && hourRange(slot) !== null && (
                <span className="tabular-nums text-text-secondary">
                  {hourRange(slot)}
                </span>
              )}
            </>
          )}
        </li>
      ))}
    </ol>
  );
}

function Nights({ read }: { read?: SleepRead }) {
  const nights = useSleepNights(read);
  return <SleepSection nights={nights} />;
}
