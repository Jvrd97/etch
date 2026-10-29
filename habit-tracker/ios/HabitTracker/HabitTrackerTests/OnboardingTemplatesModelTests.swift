// [review:need-review] PHASE-01/267
// summary: tests of the templates step — load through the read cache (fresh, offline with the cached moment, nothing cached, not configured), an added template cannot be ticked, an apply sends only the ticked keys and names the skipped ones by name, a failed apply keeps the pick, a double tap sends once, dismiss and reopen read the catalog again
import XCTest
@testable import HabitTracker

@MainActor
final class OnboardingTemplatesModelTests: XCTestCase {
    private let moment = Date(timeIntervalSince1970: 1_800_000_000)

    private func make(_ api: MockOnboardingAPI, store: CacheStore = InMemoryCacheStore()) -> OnboardingTemplatesModel {
        OnboardingTemplatesModel(api: api, cacheStore: store, now: { self.moment })
    }

    func testLoadShowsTheCatalogWithoutApplyingAnything() async {
        let api = MockOnboardingAPI()
        let model = make(api)
        await model.load()
        XCTAssertEqual(model.loadState, .loaded)
        XCTAssertEqual(model.templates.map(\.key), ["sleep", "water", "steps"])
        XCTAssertTrue(model.selected.isEmpty)
        XCTAssertFalse(model.canApply)
        XCTAssertTrue(api.appliedTemplateKeys.isEmpty)
        XCTAssertNil(model.offlineAsOf)
    }

    func testOfflineShowsTheLastCatalogWithItsMoment() async {
        let store = InMemoryCacheStore()
        let online = make(MockOnboardingAPI(), store: store)
        await online.load()
        let api = MockOnboardingAPI()
        api.templatesHandler = { throw APIClientError.transport(code: -1009) }
        let offline = make(api, store: store)
        await offline.load()
        XCTAssertEqual(offline.loadState, .loaded)
        XCTAssertEqual(offline.templates.count, 3)
        XCTAssertEqual(offline.offlineAsOf, moment)
    }

    func testOfflineWithNothingCachedIsAnErrorThatRetries() async {
        let api = MockOnboardingAPI()
        api.templatesHandler = { throw APIClientError.transport(code: -1009) }
        let model = make(api)
        await model.load()
        XCTAssertEqual(model.loadState, .failure("Нет связи с сервером"))
        api.templatesHandler = { OnboardingFixtures.catalog }
        await model.load()
        XCTAssertEqual(model.loadState, .loaded)
    }

    func testNotConfiguredNamesTheSettings() async {
        let model = OnboardingTemplatesModel(apiProvider: { nil }, cacheStore: InMemoryCacheStore())
        await model.load()
        XCTAssertEqual(model.loadState, .failure(OnboardingMessages.notConfigured))
    }

    func testAnAddedTemplateCannotBeTicked() async {
        let model = make(MockOnboardingAPI())
        await model.load()
        model.toggle("water")
        XCTAssertTrue(model.selected.isEmpty)
        model.toggle("sleep")
        XCTAssertEqual(model.selected, ["sleep"])
        model.toggle("sleep")
        XCTAssertTrue(model.selected.isEmpty)
    }

    func testApplySendsOnlyTheTickedKeysAndNamesTheSkippedOnes() async {
        let api = MockOnboardingAPI()
        api.applyTemplatesHandler = { _ in
            TemplateApplyResponseDTO(categories: [OnboardingFixtures.category(1, "Сон")], skipped: ["steps", "ghost"])
        }
        let model = make(api)
        await model.load()
        model.toggle("sleep")
        model.toggle("steps")
        await model.apply()
        XCTAssertEqual(api.appliedTemplateKeys, [["sleep", "steps"]])
        XCTAssertEqual(model.step, .applied(added: ["Сон"], skipped: ["Шаги", "ghost"]))
        XCTAssertTrue(model.selected.isEmpty)
    }

    func testFailedApplyKeepsThePickForOneTapRetry() async {
        let api = MockOnboardingAPI()
        api.applyTemplatesHandler = { _ in throw APIClientError.unexpectedStatus(500) }
        let model = make(api)
        await model.load()
        model.toggle("sleep")
        await model.apply()
        XCTAssertEqual(model.applyError, "Сервер ответил ошибкой 500")
        XCTAssertEqual(model.selected, ["sleep"])
        XCTAssertEqual(model.step, .open)
        api.applyTemplatesHandler = { _ in TemplateApplyResponseDTO(categories: [OnboardingFixtures.category(1, "Сон")], skipped: []) }
        await model.apply()
        XCTAssertNil(model.applyError)
        XCTAssertEqual(model.step, .applied(added: ["Сон"], skipped: []))
    }

    func testApplyWithNothingTickedSendsNothing() async {
        let api = MockOnboardingAPI()
        let model = make(api)
        await model.load()
        await model.apply()
        XCTAssertTrue(api.appliedTemplateKeys.isEmpty)
    }

    func testTwoTapsWhileTheFirstIsInFlightSendOnce() async {
        let api = MockOnboardingAPI()
        api.applyTemplatesHandler = { _ in
            try await Task.sleep(nanoseconds: 100_000_000)
            return TemplateApplyResponseDTO(categories: [OnboardingFixtures.category(1, "Сон")], skipped: [])
        }
        let model = make(api)
        await model.load()
        model.toggle("sleep")
        async let first: Void = model.apply()
        await Task.yield()
        async let second: Void = model.apply()
        _ = await (first, second)
        XCTAssertEqual(api.appliedTemplateKeys.count, 1)
    }

    func testDismissThenReopenReadsTheCatalogAgain() async {
        let api = MockOnboardingAPI()
        let model = make(api)
        await model.load()
        model.dismiss()
        XCTAssertEqual(model.step, .dismissed)
        api.templatesHandler = { [OnboardingFixtures.template("sleep", "Сон", added: true)] }
        await model.reopen()
        XCTAssertEqual(model.step, .open)
        XCTAssertEqual(model.templates.map(\.added), [true])
    }

    func testAFreshCatalogDropsATickOfATemplateAddedMeanwhile() async {
        let api = MockOnboardingAPI()
        let model = make(api)
        await model.load()
        model.toggle("sleep")
        api.templatesHandler = { [OnboardingFixtures.template("sleep", "Сон", added: true)] }
        await model.load()
        XCTAssertTrue(model.selected.isEmpty)
    }
}
