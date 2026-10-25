// [review:need-review] PHASE-03/155, PHASE-03/217
// summary: turns app sightings into title-free activity intervals; a return to the same app within 30 seconds is a micro-switch inside the interval, not a new one; an interval open for 5 minutes is cut so a kill loses at most that
import Foundation

struct AppSighting: Equatable {
    let bundleID: String
    let date: Date
}

struct ActivityInterval: Equatable, Encodable {
    let bundleID: String
    let startedAt: Date
    let endedAt: Date
    let localDate: String
    let utcOffsetMinutes: Int
    let title: String? = nil
    let titleSource = "dropped"
    let idleSeconds = 0
    let switchCount: Int
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
/// `continuityWindow` or longer (sleep, stopped sampling) ends an interval at
/// its last sighting.
///
/// An interval has no upper bound while it is open, and a killed agent never
/// closes it. `checkpoint()` cuts a long interval so only the part since the
/// last cut can be lost.
struct IntervalBuilder {
    static let continuityWindow: TimeInterval = 30
    static let checkpointInterval: TimeInterval = 5 * 60

    private struct OpenInterval {
        let bundleID: String
        let startedAt: Date
        var lastSeen: Date
        var switchCount: Int
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
        guard var active = current else {
            current = OpenInterval(bundleID: sighting.bundleID, startedAt: sighting.date, lastSeen: sighting.date, switchCount: 0)
            return []
        }

        guard var away = excursion else {
            guard isContinuous(from: active.lastSeen, to: sighting.date) else {
                current = OpenInterval(bundleID: sighting.bundleID, startedAt: sighting.date, lastSeen: sighting.date, switchCount: 0)
                return close(active, at: active.lastSeen)
            }
            if sighting.bundleID == active.bundleID {
                active.lastSeen = sighting.date
                current = active
            } else {
                excursion = Excursion(bundleID: sighting.bundleID, startedAt: sighting.date, lastSeen: sighting.date)
            }
            return []
        }

        let withinWindow = isContinuous(from: away.startedAt, to: sighting.date)
        if sighting.bundleID == active.bundleID, withinWindow {
            active.lastSeen = sighting.date
            active.switchCount += 1
            current = active
            excursion = nil
            return []
        }
        let staysOnVisit = sighting.bundleID == away.bundleID && isContinuous(from: away.lastSeen, to: sighting.date)
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
    /// in front the interval may still be resumed as one, so it waits.
    mutating func checkpoint() -> [ActivityInterval] {
        guard let active = current, excursion == nil,
              active.lastSeen.timeIntervalSince(active.startedAt) >= Self.checkpointInterval else { return [] }
        current = OpenInterval(bundleID: active.bundleID, startedAt: active.lastSeen, lastSeen: active.lastSeen, switchCount: 0)
        return close(active, at: active.lastSeen)
    }

    /// Closes whatever is open as of `date` and returns it.
    mutating func finish(at date: Date) -> [ActivityInterval] {
        guard let active = current else { return [] }
        current = nil
        guard let away = excursion else {
            return close(active, at: continuousEnd(lastSeen: active.lastSeen, now: date))
        }
        excursion = nil
        let visited = OpenInterval(bundleID: away.bundleID, startedAt: away.startedAt, lastSeen: away.lastSeen, switchCount: 0)
        return close(active, at: away.startedAt) + close(visited, at: continuousEnd(lastSeen: away.lastSeen, now: date))
    }

    private func isContinuous(from earlier: Date, to later: Date) -> Bool {
        let gap = later.timeIntervalSince(earlier)
        return gap >= 0 && gap < Self.continuityWindow
    }

    /// An interval runs up to `now` unless the app went unseen for the whole window.
    private func continuousEnd(lastSeen: Date, now: Date) -> Date {
        isContinuous(from: lastSeen, to: now) ? now : lastSeen
    }

    /// A zero-length interval carries no time and is not reported.
    private func close(_ interval: OpenInterval, at end: Date) -> [ActivityInterval] {
        guard end > interval.startedAt else { return [] }
        let dateFormatter = ISO8601DateFormatter()
        dateFormatter.formatOptions = [.withFullDate]
        dateFormatter.timeZone = timeZone
        return [ActivityInterval(
            bundleID: interval.bundleID,
            startedAt: interval.startedAt,
            endedAt: end,
            localDate: dateFormatter.string(from: interval.startedAt),
            utcOffsetMinutes: timeZone.secondsFromGMT(for: interval.startedAt) / 60,
            switchCount: interval.switchCount
        )]
    }
}
