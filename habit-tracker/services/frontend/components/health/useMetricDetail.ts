"use client";
// [review:need-review] PHASE-02/68
// summary: loads the two reads behind the metric detail screen — the daily series of a period and the hours of the chosen day — each as a discriminated state; a stale answer is dropped when the period or the day changed while it was in flight

import { useEffect, useState } from "react";
// A namespace import read at call time: suites that mock `@/lib/api` with a
// fixed list of names keep linking every screen that renders Health.
import * as api from "@/lib/api";
import type { HealthMetricDays, HealthMetricHours } from "@/lib/api";
import { localDate } from "@/lib/health-metrics";
import { shiftDate } from "./useSleepNights";

export type LoadState<T> =
  { status: "loading" } | { status: "error" } | { status: "ready"; data: T };

export type DaysRead = (
  identifier: string,
  dateFrom: string,
  dateTo: string,
) => Promise<HealthMetricDays>;
export type HoursRead = (
  identifier: string,
  date: string,
) => Promise<HealthMetricHours>;

const DAYS_READ: DaysRead = (identifier, from, to) =>
  api.healthAPI.getMetricDays(identifier, from, to);
const HOURS_READ: HoursRead = (identifier, date) =>
  api.healthAPI.getMetricHours(identifier, date);

function useLoad<T>(
  load: (() => Promise<T>) | null,
  deps: readonly unknown[],
): LoadState<T> {
  const [state, setState] = useState<LoadState<T>>({ status: "loading" });

  useEffect(() => {
    if (load === null) return;
    let alive = true;
    setState({ status: "loading" });
    // `Promise.resolve().then` also turns a synchronous throw from `load` into a rejection.
    Promise.resolve()
      .then(load)
      .then((data) => {
        if (alive) setState({ status: "ready", data });
      })
      .catch(() => {
        if (alive) setState({ status: "error" });
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `deps` is the caller's explicit list of what the read depends on
  }, deps);

  return state;
}

/** The daily series over the last `periodDays` days, today included. */
export function useMetricDays(
  identifier: string,
  periodDays: number,
  read: DaysRead = DAYS_READ,
): LoadState<HealthMetricDays> {
  return useLoad(() => {
    const today = localDate();
    return read(identifier, shiftDate(today, 1 - periodDays), today);
  }, [identifier, periodDays, read]);
}

/** The hours of one day; `enabled` is false for a metric that has none (sleep). */
export function useMetricHours(
  identifier: string,
  day: string,
  enabled: boolean,
  read: HoursRead = HOURS_READ,
): LoadState<HealthMetricHours> {
  return useLoad(enabled ? () => read(identifier, day) : null, [
    identifier,
    day,
    enabled,
    read,
  ]);
}
