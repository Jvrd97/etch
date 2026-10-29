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

    private func render<V: View>(_ view: V) throws -> UIImage {
        let renderer = ImageRenderer(
            content: view.frame(width: 360).background(Color.black).environment(\.colorScheme, .dark)
        )
        renderer.scale = 2
        return try XCTUnwrap(renderer.uiImage)
    }
}
