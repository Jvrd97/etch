// [review:need-review] PHASE-02/68
// summary: render tests of the metric detail screen — the daily series and a period switch, the day switch that re-reads the hours, 24 hour rows with empty hours kept as "нет данных", the min–max range of a discrete hour, a day with no data, a failed read, and sleep showing nights instead of hours

import { afterEach, describe, expect, it, mock } from "bun:test";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { HealthMetricDays, HealthMetricHours } from "@/lib/api";
import { hourRange, hourSlots, metricHref } from "@/lib/health";
import MetricDetail from "./MetricDetail";

afterEach(cleanup);

const HEART_DAYS: HealthMetricDays = {
  identifier: "heart",
  display_name: "Пульс",
  kind: "discrete",
  canonical_unit: "count/min",
  days: [
    { date: "2026-10-19", value: 61 },
    { date: "2026-10-20", value: 72.4 },
  ],
};

function hoursOf(date: string): HealthMetricHours {
  return {
    identifier: "heart",
    display_name: "Пульс",
    kind: "discrete",
    canonical_unit: "count/min",
    date,
    hours:
      date === "2026-10-20"
        ? [
            { hour: 5, value: 56, min: 54, max: 58, sample_count: 2 },
            { hour: 11, value: 90, min: 90, max: 90, sample_count: 1 },
          ]
        : [],
  };
}

function setup(days: HealthMetricDays = HEART_DAYS) {
  const readDays = mock((_id: string, _from: string, _to: string) =>
    Promise.resolve(days),
  );
  const readHours = mock((_id: string, date: string) =>
    Promise.resolve(hoursOf(date)),
  );
  const view = render(
    <MetricDetail
      identifier="heart"
      backHref="/health"
      readDays={readDays}
      readHours={readHours}
      readNights={() => Promise.resolve({ nights: [] })}
    />,
  );
  return { readDays, readHours, view };
}

describe("helpers", () => {
  it("keeps an hour without data as an empty slot in a 24-hour grid", () => {
    const slots = hourSlots([
      { hour: 8, value: 1, min: 1, max: 1, sample_count: 1 },
    ]);
    expect(slots).toHaveLength(24);
    expect(slots[8]?.value).toBe(1);
    expect(slots.filter((slot) => slot === null)).toHaveLength(23);
  });

  it("prints a range only when the readings of the hour differ", () => {
    expect(
      hourRange({ hour: 5, value: 56, min: 54, max: 58, sample_count: 2 }),
    ).toBe("54–58");
    expect(
      hourRange({ hour: 11, value: 90, min: 90, max: 90, sample_count: 1 }),
    ).toBeNull();
  });

  it("builds the row link for the desktop and the phone shells", () => {
    expect(metricHref("/health", "HKQuantityTypeIdentifierStepCount")).toBe(
      "/health/HKQuantityTypeIdentifierStepCount",
    );
    expect(metricHref("/m/health", "a b")).toBe("/m/health/a%20b");
  });
});

describe("MetricDetail", () => {
  it("opens on the latest day with data and lists 24 hours, empty ones marked", async () => {
    const { readHours } = setup();

    await waitFor(() =>
      expect(screen.getByRole("list", { name: "Часы дня" })).toBeDefined(),
    );
    expect(readHours).toHaveBeenCalledWith("heart", "2026-10-20");
    const rows = within(
      screen.getByRole("list", { name: "Часы дня" }),
    ).getAllByRole("listitem");
    expect(rows).toHaveLength(24);
    expect(within(rows[5]).getByText("56")).toBeDefined();
    expect(within(rows[5]).getByText("54–58")).toBeDefined();
    expect(within(rows[11]).getByText("90")).toBeDefined();
    expect(within(rows[0]).getByText("нет данных")).toBeDefined();
  });

  it("switches the day and re-reads its hours", async () => {
    const { readHours } = setup();
    await waitFor(() =>
      expect(screen.getByRole("list", { name: "Часы дня" })).toBeDefined(),
    );

    fireEvent.click(screen.getByRole("button", { name: /19 окт/ }));

    await waitFor(() =>
      expect(readHours).toHaveBeenCalledWith("heart", "2026-10-19"),
    );
    await waitFor(() =>
      expect(
        within(screen.getByRole("list", { name: "Часы дня" })).getAllByText(
          "нет данных",
        ).length,
      ).toBe(24),
    );
  });

  it("re-reads the series when the period changes", async () => {
    const { readDays } = setup();
    await waitFor(() => expect(readDays).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "7 дней" }));

    await waitFor(() => expect(readDays).toHaveBeenCalledTimes(2));
  });

  it("says so when the metric has no day at all", async () => {
    setup({ ...HEART_DAYS, days: [] });

    await waitFor(() =>
      expect(screen.getByText(/Данных по метрике нет/)).toBeDefined(),
    );
    expect(screen.queryByRole("list", { name: "Часы дня" })).toBeNull();
  });

  it("reports a failed read of the series", async () => {
    render(
      <MetricDetail
        identifier="heart"
        backHref="/health"
        readDays={() => Promise.reject(new Error("down"))}
        readHours={() => Promise.reject(new Error("down"))}
        readNights={() => Promise.resolve({ nights: [] })}
      />,
    );

    await waitFor(() =>
      expect(screen.getByText("Не удалось загрузить метрику")).toBeDefined(),
    );
  });

  it("shows nights, not hours, for sleep", async () => {
    const readHours = mock((_id: string, _date: string) =>
      Promise.resolve(hoursOf("2026-10-20")),
    );
    render(
      <MetricDetail
        identifier="sleep"
        backHref="/health"
        readDays={() =>
          Promise.resolve({
            identifier: "sleep",
            display_name: "Сон",
            kind: "sleep",
            canonical_unit: "min",
            days: [{ date: "2026-10-20", value: 390 }],
          })
        }
        readHours={readHours}
        readNights={() =>
          Promise.resolve({
            nights: [
              {
                date: "2026-10-20",
                bedtime: "2026-10-19T23:00:00+02:00",
                wake_time: "2026-10-20T07:00:00+02:00",
                in_bed_min: 480,
                asleep_min: 390,
                awake_min: 30,
                core_min: 210,
                deep_min: 60,
                rem_min: 120,
                unspecified_min: 0,
              },
            ],
          })
        }
      />,
    );

    await waitFor(() =>
      expect(screen.getByText(/отбой 23:00, подъём 07:00/)).toBeDefined(),
    );
    expect(screen.queryByRole("list", { name: "Часы дня" })).toBeNull();
    expect(readHours).not.toHaveBeenCalled();
  });
});
