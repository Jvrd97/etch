// [review:need-review] PHASE-03/222
// summary: tests of the week overview — slides from the fixture answer, screen states (loading, failed, empty, unfinished week with its note) and a still render of a slide and the feed with Reduce Motion that carries the final figures
import SwiftUI
import XCTest
@testable import HabitTracker

@MainActor
final class WeekOverviewTests: XCTestCase {
    func testLoadingStates() throws {
        XCTAssertEqual(WeekOverview.state(loadState: .loading, review: nil, note: nil), .loading)
        XCTAssertEqual(WeekOverview.state(loadState: .idle, review: nil, note: nil), .loading)
        XCTAssertEqual(WeekOverview.state(loadState: .failure("нет сети"), review: nil, note: nil), .failed("нет сети"))
    }

    func testEmptyWeek() throws {
        let review = try WeekFixtures.emptyWeek()
        XCTAssertEqual(WeekOverview.state(loadState: .loaded, review: review, note: nil), .empty)
    }

    func testUnfinishedWeekKeepsItsNote() throws {
        let review = try WeekFixtures.runningWeek()
        let state = WeekOverview.state(loadState: .loaded, review: review, note: "Неделя не закончилась")
        guard case .ready(let slides, let note) = state else { return XCTFail("expected ready, got \(state)") }
        XCTAssertEqual(note, "Неделя не закончилась")
        XCTAssertEqual(slides.first?.kind, .verdict)
        XCTAssertEqual(slides.first?.figure, review.totals.wonDays)
    }

    func testSlidesCarryTheServerFigures() throws {
        let review = try WeekFixtures.review()
        let slides = WeekOverview.slides(review)
        XCTAssertEqual(slides.map(\.id).first, .verdict)
        XCTAssertEqual(Set(slides.map(\.id)).count, slides.count)
        let tasks = try XCTUnwrap(slides.first { $0.kind == .tasks })
        XCTAssertEqual(tasks.figure, review.totals.tasksDone)
        XCTAssertEqual(tasks.figureText, WeekFormat.number(review.totals.tasksDone))
        let verdict = try XCTUnwrap(slides.first)
        XCTAssertTrue(verdict.caption.contains(String(review.totals.closedDays)))
    }

    func testFormats() {
        XCTAssertEqual(WeekOverviewFormat.percent.text(80), "80%")
        XCTAssertEqual(WeekOverviewFormat.minutes.text(75), WeekFormat.minutes(75))
    }

    /// The still view (Reduce Motion) renders at once with the final figure, no animation to wait for.
    func testStillRenderOfSlideAndFeed() throws {
        let review = try WeekFixtures.review()
        let slide = try XCTUnwrap(WeekOverview.slides(review).first { $0.kind == .tasks })
        let slideImage = try render(WeekOverviewSlideView(slide: slide, reduceMotion: true))
        let feedImage = try render(WeekOverviewFeedView(review: review, reduceMotion: true))
        XCTAssertGreaterThan(slideImage.size.height, 0)
        XCTAssertGreaterThan(feedImage.size.height, slideImage.size.height / 2)
        for (name, image) in [("slide-still", slideImage), ("feed-still", feedImage)] {
            let attachment = XCTAttachment(image: image)
            attachment.name = name
            attachment.lifetime = .keepAlways
            add(attachment)
        }
    }

    func testPlanFractionIsShareOf100() {
        XCTAssertEqual(WeekOverview.fraction(40, scale: WeekOverview.planScale), 0.4, accuracy: 0.0001)
        XCTAssertEqual(WeekOverview.fraction(nil, scale: 100), 0)
        XCTAssertEqual(WeekOverview.fraction(150, scale: 100), 1)
        XCTAssertEqual(WeekOverview.fraction(30, scale: 60), 0.5, accuracy: 0.0001)
    }

    func testTasksSlideDroppedWithoutTasks() throws {
        let review = try WeekFixtures.review { object in
            var totals = object["totals"] as? [String: Any] ?? [:]
            totals["tasks_total"] = 0
            totals["tasks_done"] = 0
            object["totals"] = totals
        }
        XCTAssertFalse(WeekOverview.slides(review).contains { $0.kind == .tasks })
    }

    func testTimeSlideFallsBackToRoleMinutes() throws {
        for work: Any in [NSNull(), 0] {
            let review = try WeekFixtures.review { object in
                var totals = object["totals"] as? [String: Any] ?? [:]
                totals["work_minutes"] = work
                totals["role_minutes"] = 90
                object["totals"] = totals
            }
            XCTAssertFalse(WeekOverview.usesWorkMinutes(review))
            let slide = try XCTUnwrap(WeekOverview.slides(review).first { $0.kind == .time })
            XCTAssertEqual(slide.figure, 90)
            XCTAssertEqual(slide.title, "Время по ролям")
        }
    }

    func testNoHabitStreaksAndNoBestWorstDay() throws {
        let review = try WeekFixtures.review { object in
            object["habit_streaks"] = [Any]()
            object["best_day"] = NSNull()
            object["worst_day"] = NSNull()
        }
        let kinds = WeekOverview.slides(review).map(\.kind)
        XCTAssertFalse(kinds.contains(.habitStreak))
        XCTAssertFalse(kinds.contains(.days))
    }

    func testDayStreakAndHabitStreakAreSeparateSlides() throws {
        let review = try WeekFixtures.review { object in
            var totals = object["totals"] as? [String: Any] ?? [:]
            totals["day_streak_end"] = 4
            object["totals"] = totals
            object["habit_streaks"] = [["category_id": 1, "name": "Без сахара", "current_streak": 9, "relapses": 2]]
        }
        let slides = WeekOverview.slides(review)
        let day = try XCTUnwrap(slides.first { $0.kind == .dayStreak })
        XCTAssertEqual(day.title, "Серия дней")
        XCTAssertEqual(day.figure, 4)
        let habit = try XCTUnwrap(slides.first { $0.kind == .habitStreak })
        XCTAssertEqual(habit.figure, 9)
        XCTAssertTrue(habit.caption.contains("за неделю"))
        XCTAssertNotEqual(habit.title, day.title)
    }

    func testVerdictLineReachesTheCaption() throws {
        let review = try WeekFixtures.review { $0["verdict_line"] = "Неделя выиграна: 5 из 7" }
        let slide = try XCTUnwrap(WeekOverview.slides(review).first)
        XCTAssertTrue(slide.caption.contains("Неделя выиграна: 5 из 7"))
    }

    func testReduceMotionStartsFinished() {
        XCTAssertEqual(MotionProgress.initial(reduceMotion: true), 1)
        XCTAssertEqual(MotionProgress.initial(reduceMotion: false), 0)
    }

    private static let renderWidth: CGFloat = 360
    private static let renderScale: CGFloat = 2

    private func render<V: View>(_ view: V) throws -> UIImage {
        let renderer = ImageRenderer(
            content: view.frame(width: Self.renderWidth).background(Color.black).environment(\.colorScheme, .dark)
        )
        renderer.scale = Self.renderScale
        return try XCTUnwrap(renderer.uiImage)
    }
}
