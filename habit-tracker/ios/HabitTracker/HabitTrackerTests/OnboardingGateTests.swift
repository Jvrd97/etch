// [review:need-review] PHASE-01/267
// summary: tests of the first-launch entry — the sheet opens once when the server has no categories, categories present or a closed sheet mark the offer as made, a failed read and a missing server address open nothing and mark nothing, an offered install is never asked again
import XCTest
@testable import HabitTracker

private final class MemoryOfferStore: OnboardingOfferStore {
    var wasOffered = false
    func markOffered() { wasOffered = true }
}

@MainActor
final class OnboardingGateTests: XCTestCase {
    func testEmptyServerOpensTheOnboardingAndTheCloseMarksIt() async {
        let api = MockOnboardingAPI()
        let store = MemoryOfferStore()
        let gate = OnboardingGateModel(apiProvider: { api }, store: store)
        await gate.check()
        XCTAssertTrue(gate.isPresented)
        XCTAssertFalse(store.wasOffered)
        gate.finish()
        XCTAssertFalse(gate.isPresented)
        XCTAssertTrue(store.wasOffered)
    }

    func testExistingCategoriesMeanNoOfferNow() async {
        let api = MockOnboardingAPI()
        api.categoriesHandler = { [OnboardingFixtures.category(1, "Сон")] }
        let store = MemoryOfferStore()
        let gate = OnboardingGateModel(apiProvider: { api }, store: store)
        await gate.check()
        XCTAssertFalse(gate.isPresented)
        XCTAssertTrue(store.wasOffered)
    }

    func testAFailedReadOpensNothingAndMarksNothing() async {
        let api = MockOnboardingAPI()
        api.categoriesHandler = { throw APIClientError.transport(code: -1009) }
        let store = MemoryOfferStore()
        let gate = OnboardingGateModel(apiProvider: { api }, store: store)
        await gate.check()
        XCTAssertFalse(gate.isPresented)
        XCTAssertFalse(store.wasOffered)
    }

    func testNoServerAddressOpensNothing() async {
        let store = MemoryOfferStore()
        let gate = OnboardingGateModel(apiProvider: { nil }, store: store)
        await gate.check()
        XCTAssertFalse(gate.isPresented)
        XCTAssertFalse(store.wasOffered)
    }

    func testAnAlreadyOfferedInstallIsNotAskedAgain() async {
        let api = MockOnboardingAPI()
        let store = MemoryOfferStore()
        store.wasOffered = true
        let gate = OnboardingGateModel(apiProvider: { api }, store: store)
        await gate.check()
        XCTAssertFalse(gate.isPresented)
    }

    func testTheOfferIsRememberedInUserDefaults() {
        let defaults = UserDefaults(suiteName: "onboarding-gate-tests")!
        defaults.removePersistentDomain(forName: "onboarding-gate-tests")
        let store = UserDefaultsOnboardingOfferStore(defaults: defaults)
        XCTAssertFalse(store.wasOffered)
        store.markOffered()
        XCTAssertTrue(UserDefaultsOnboardingOfferStore(defaults: defaults).wasOffered)
    }

    func testMoreListsTheOnboarding() {
        XCTAssertTrue(MoreDestination.allCases.contains(.onboarding))
        XCTAssertEqual(MoreDestination.onboarding.title, "Онбординг")
    }
}
