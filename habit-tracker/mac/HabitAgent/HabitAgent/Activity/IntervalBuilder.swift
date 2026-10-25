// [review:need-review] PHASE-03/155, PHASE-03/217, PHASE-03/172
// summary: turns app sightings into title-free activity intervals; a return to the same app within 30 seconds is a micro-switch inside the interval, not a new one; an interval open for 5 minutes is cut on fresh input, so a kill loses about 5 minutes of work (a pause in input is not cut, and its time is not work anyway); pauses in input become idle_seconds, and a long absence or a sleep closes the interval at the last input
import Foundation

struct AppSighting: Equatable {
    let bundleID: String
    let date: Date
    /// Seconds since the last keyboard or mouse event when the app was seen.
    let idleSeconds: TimeInterval

    init(bundleID: String, date: Date, idleSeconds: TimeInterval = 0) {
        self.bundleID = bundleID
        self.date = date
        self.idleSeconds = idleSeconds
    }
}

struct ActivityInterval: Equatable, Encodable {
    let bundleID: String
    let startedAt: Date
    let endedAt: Date
    let localDate: String
    let utcOffsetMinutes: Int
    let title: String? = nil
    let titleSource = "dropped"
    let switchCount: Int
    /// Time without input inside the interval, counted from pauses longer than `IdleMonitor.idleThreshold`.
    var idleSeconds = 0
    let source = "agent"

    enum CodingKeys: String, CodingKey {
        case bundleID = "bundle_id"
        case startedAt = "started_at"
        case endedAt = "ended_at"
        case localDate = "local_date"
        case utcOffsetMinutes = "utc_offset_minutes"
        case title
        case titleSource = "title_source"
        case idleSeconds = "idle_seconds"
        case switchCount = "switch_count"
        case source
    }
}

/// Coalesces sightings of the foreground app into intervals (ADR-0019).
///
/// Sightings of one app less than `continuityWindow` apart extend its interval.
/// Leaving for another app and coming back within `continuityWindow` keeps the
/// interval open and counts one micro-switch (`switch_count`); the short visit
/// is absorbed. A visit that lasts `continuityWindow` or longer — or turns into
/// a third app — closes the interval at the moment of leaving. Silence of
/// `silenceWindow` or longer (sleep, stopped sampling) ends an interval at
/// its last sighting.
///
/// Sightings carry the seconds since the last input. A pause longer than
/// `IdleMonitor.idleThreshold` stays in the interval and adds to `idle_seconds`; an absence of
/// `IdleMonitor.awayThreshold` or a sleep (`finish(at:lastInput:)`) ends the interval at the
/// last input, so the time away belongs to nothing.
///
/// An interval has no upper bound while it is open, and a killed agent never
/// closes it. `checkpoint()` cuts a long interval so only the work since the
/// last cut can be lost: about `checkpointInterval` of work, while a pause in input
/// waits for the away rule and is not bounded, as it is not work.
struct IntervalBuilder {
    static let continuityWindow: TimeInterval = 30
    /// Longer than the idle sampling period, or every idle sighting would start a new interval.
    static let silenceWindow: TimeInterval = IdleMonitor.idlePeriod + silenceMargin
    /// Room for a late timer on top of the idle period. The timer's own tolerance takes a fifth of the period (6 s);
    /// the rest, 24 s, is left for App Nap and a busy main thread, which a 15 s margin (9 s left) did not cover.
    static let silenceMargin: TimeInterval = IdleMonitor.idlePeriod
    static let checkpointInterval: TimeInterval = 5 * 60

    private struct OpenInterval {
        let bundleID: String
        let startedAt: Date
        var lastSeen: Date
        var switchCount: Int
        var idle: TimeInterval = 0
        /// How much of the pause still going on is already in `idle`.
        var pauseCounted: TimeInterval = 0
        /// Seconds since the last input at the latest sighting.
        var lastIdle: TimeInterval = 0

        mutating func observe(_ sighting: AppSighting) {
            lastSeen = sighting.date
            lastIdle = sighting.idleSeconds
            guard sighting.idleSeconds > IdleMonitor.idleThreshold else {
                pauseCounted = 0
                return
            }
            let pause = min(sighting.idleSeconds, sighting.date.timeIntervalSince(startedAt))
            idle += max(0, pause - pauseCounted)
            pauseCounted = max(pause, pauseCounted)
        }
    }

    /// Another app in front while `current` may still be resumed.
    private struct Excursion {
        let bundleID: String
        let startedAt: Date
        var lastSeen: Date
    }

    private let timeZone: TimeZone
    private var current: OpenInterval?
    private var excursion: Excursion?

    init(timeZone: TimeZone = .current) {
        self.timeZone = timeZone
    }

    /// Feeds one sighting and returns the intervals it closed.
    mutating func record(_ sighting: AppSighting) -> [ActivityInterval] {
        if sighting.idleSeconds >= IdleMonitor.awayThreshold {
            return finish(at: sighting.date, lastInput: sighting.date.addingTimeInterval(-sighting.idleSeconds))
        }
        guard var active = current else {
            current = OpenInterval(bundleID: sighting.bundleID, startedAt: sighting.date, lastSeen: sighting.date, switchCount: 0)
            return []
        }

        guard var away = excursion else {
            guard isContinuous(from: active.lastSeen, to: sighting.date, within: Self.silenceWindow) else {
                current = OpenInterval(bundleID: sighting.bundleID, startedAt: sighting.date, lastSeen: sighting.date, switchCount: 0)
                return close(active, at: active.lastSeen)
            }
            if sighting.bundleID == active.bundleID {
                active.observe(sighting)
                current = active
            } else {
                excursion = Excursion(bundleID: sighting.bundleID, startedAt: sighting.date, lastSeen: sighting.date)
            }
            return []
        }

        let withinWindow = isContinuous(from: away.startedAt, to: sighting.date, within: Self.continuityWindow)
        if sighting.bundleID == active.bundleID, withinWindow {
            active.observe(sighting)
            active.switchCount += 1
            current = active
            excursion = nil
            return []
        }
        let staysOnVisit = sighting.bundleID == away.bundleID && isContinuous(from: away.lastSeen, to: sighting.date, within: Self.silenceWindow)
        if staysOnVisit, withinWindow {
            away.lastSeen = sighting.date
            excursion = away
            return []
        }

        // The visit outlived the window or led elsewhere: the interval ends
        // where it was left, and the visited app becomes the open interval.
        let left = close(active, at: away.startedAt)
        current = OpenInterval(bundleID: away.bundleID, startedAt: away.startedAt, lastSeen: away.lastSeen, switchCount: 0)
        excursion = nil
        return left + record(sighting)
    }

    /// Closes the open interval at its last sighting once it has run for `checkpointInterval`
    /// and opens its continuation from there; call it after `record`. While another app is
    /// in front the interval may still be resumed as one, and it cuts only on a sighting with
    /// fresh input (under `IdleMonitor.activePeriod`): after that the person may have left, the
    /// away rule or a sleep would end the interval at the last input, and a cut made at the
    /// last sighting would send the time after that input as work. In both cases it waits.
    mutating func checkpoint() -> [ActivityInterval] {
        guard let active = current, excursion == nil, active.lastIdle < IdleMonitor.activePeriod,
              active.lastSeen.timeIntervalSince(active.startedAt) >= Self.checkpointInterval else { return [] }
        current = OpenInterval(bundleID: active.bundleID, startedAt: active.lastSeen, lastSeen: active.lastSeen, switchCount: 0)
        return close(active, at: active.lastSeen)
    }

    /// Closes whatever is open as of `date` and returns it. With `lastInput` nothing runs past
    /// it: the person left at that moment, however late the sleep or the absence was noticed.
    mutating func finish(at date: Date, lastInput: Date? = nil) -> [ActivityInterval] {
        guard let active = current else { return [] }
        current = nil
        let limit = lastInput ?? .distantFuture
        guard let away = excursion else {
            return close(active, at: min(continuousEnd(lastSeen: active.lastSeen, now: date), limit))
        }
        excursion = nil
        let visited = OpenInterval(bundleID: away.bundleID, startedAt: away.startedAt, lastSeen: away.lastSeen, switchCount: 0)
        return close(active, at: min(away.startedAt, limit))
            + close(visited, at: min(continuousEnd(lastSeen: away.lastSeen, now: date), limit))
    }

    private func isContinuous(from earlier: Date, to later: Date, within window: TimeInterval) -> Bool {
        let gap = later.timeIntervalSince(earlier)
        return gap >= 0 && gap < window
    }

    /// An interval runs up to `now` unless the app went unseen for the whole silence window.
    private func continuousEnd(lastSeen: Date, now: Date) -> Date {
        isContinuous(from: lastSeen, to: now, within: Self.silenceWindow) ? now : lastSeen
    }

    /// A zero-length interval carries no time and is not reported. Ending before the last sighting
    /// cuts off the pause still going on, so it leaves `idle_seconds` too.
    private func close(_ interval: OpenInterval, at end: Date) -> [ActivityInterval] {
        guard end > interval.startedAt else { return [] }
        let cutOff = end < interval.lastSeen ? interval.pauseCounted : 0
        let idle = max(0, min(interval.idle - cutOff, end.timeIntervalSince(interval.startedAt)))
        let dateFormatter = ISO8601DateFormatter()
        dateFormatter.formatOptions = [.withFullDate]
        dateFormatter.timeZone = timeZone
        return [ActivityInterval(
            bundleID: interval.bundleID,
            startedAt: interval.startedAt,
            endedAt: end,
            localDate: dateFormatter.string(from: interval.startedAt),
            utcOffsetMinutes: timeZone.secondsFromGMT(for: interval.startedAt) / 60,
            switchCount: interval.switchCount,
            idleSeconds: Int(idle.rounded())
        )]
    }
}
