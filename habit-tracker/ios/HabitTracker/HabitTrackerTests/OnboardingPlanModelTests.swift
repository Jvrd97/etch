// [review:need-review] PHASE-01/267
// summary: tests of the voice builder step — a blank text asks nothing, the plan opens with a new free category on and a clashing name or an added field off, the batch carries only the ticked operations with the edited name, a blank name blocks the apply, the words of 503/502/400/422, a failed apply keeps the preview, a new draft retires the old error, the model is only ever a fake
import XCTest
@testable import HabitTracker

@MainActor
final class OnboardingPlanModelTests: XCTestCase {
    private func drafted(_ api: MockOnboardingAPI = MockOnboardingAPI()) async -> (OnboardingPlanModel, MockOnboardingAPI) {
        let model = OnboardingPlanModel(api: api)
        model.transcript = "  хочу трекать сон  "
        await model.generate()
        return (model, api)
    }

    func testBlankTextAsksNothing() async {
        let api = MockOnboardingAPI()
        let model = OnboardingPlanModel(api: api)
        model.transcript = "   \n"
        XCTAssertFalse(model.canGenerate)
        await model.generate()
        XCTAssertTrue(api.drafts.isEmpty)
        XCTAssertEqual(model.draft, .idle)
    }

    func testDraftSendsTheTrimmedTextAndStartsWithTheSafeSwitches() async {
        let (model, api) = await drafted()
        XCTAssertEqual(api.drafts, ["хочу трекать сон"])
        XCTAssertEqual(model.opStates.map(\.enabled), [false, true, false])
        XCTAssertEqual(model.opStates.map(\.name), ["Вода", "Сон", ""])
        XCTAssertEqual(model.enabledCount, 1)
    }

    func testBatchCarriesOnlyTheTickedOperationsWithTheEditedName() async {
        let (model, api) = await drafted()
        model.setName(1, "  Сон ночной ")
        model.setEnabled(2, true)
        await model.apply()
        let sent = api.appliedPlans.first
        XCTAssertEqual(sent?.count, 2)
        guard case .createCategory(let create)? = sent?.first, case .addField(let add)? = sent?.last else {
            return XCTFail("wrong operations")
        }
        XCTAssertEqual(create.name, "Сон ночной")
        XCTAssertEqual(add.categoryId, 4)
        XCTAssertTrue(model.didApply)
    }

    func testAClashingNameBecomesSendableOnlyByTickingIt() async {
        let (model, api) = await drafted()
        model.setEnabled(1, false)
        XCTAssertFalse(model.canApply)
        await model.apply()
        XCTAssertTrue(api.appliedPlans.isEmpty)
    }

    func testABlankNameOfATickedNewCategoryBlocksTheApply() async {
        let (model, api) = await drafted()
        model.setName(1, "   ")
        XCTAssertFalse(model.canApply)
        await model.apply()
        XCTAssertTrue(api.appliedPlans.isEmpty)
        model.setName(1, "Сон")
        XCTAssertTrue(model.canApply)
    }

    func testAnEmptyPlanIsADoneDraftWithNothingToApply() async {
        let api = MockOnboardingAPI()
        api.draftHandler = { _ in OnboardingPlanDTO(operations: []) }
        let (model, _) = await drafted(api)
        XCTAssertEqual(model.draft, .done(OnboardingPlanDTO(operations: [])))
        XCTAssertFalse(model.canApply)
    }

    func testWordsOfTheDraftFailures() async {
        for (error, words) in [
            (APIClientError.unexpectedStatus(503), "На сервере не включён ИИ. Возьмите шаблоны выше или создайте категории вручную."),
            (APIClientError.unexpectedStatus(502), "Модель не ответила. Повторите."),
            (APIClientError.timeout, "Сервер не ответил вовремя"),
        ] {
            let api = MockOnboardingAPI()
            api.draftHandler = { _ in throw error }
            let (model, _) = await drafted(api)
            XCTAssertEqual(model.draft, .failure(words))
        }
    }

    func testRetryAfterAFailedDraftBuildsThePlan() async {
        let api = MockOnboardingAPI()
        api.draftHandler = { _ in throw APIClientError.unexpectedStatus(502) }
        let (model, _) = await drafted(api)
        api.draftHandler = { _ in OnboardingFixtures.plan }
        await model.generate()
        XCTAssertEqual(model.operations.count, 3)
    }

    func testRefusedPlanKeepsThePreviewAndSaysWhy() async {
        let api = MockOnboardingAPI()
        api.applyPlanHandler = { _ in throw APIClientError.unexpectedStatus(400) }
        let (model, _) = await drafted(api)
        await model.apply()
        XCTAssertEqual(model.applyError, "Сервер отклонил план: имя категории уже занято. Измените имя и повторите.")
        XCTAssertFalse(model.didApply)
        XCTAssertEqual(model.operations.count, 3)
        XCTAssertEqual(model.enabledCount, 1)
    }

    func testANewDraftRetiresTheOldApplyError() async {
        let api = MockOnboardingAPI()
        api.applyPlanHandler = { _ in throw APIClientError.unexpectedStatus(422) }
        let (model, _) = await drafted(api)
        await model.apply()
        XCTAssertNotNil(model.applyError)
        await model.generate()
        XCTAssertNil(model.applyError)
    }

    func testTwoTapsOnApplyWhileInFlightSendOnce() async {
        let api = MockOnboardingAPI()
        api.applyPlanHandler = { _ in
            try await Task.sleep(nanoseconds: 100_000_000)
            return CategoryBatchResponseDTO(categories: [], fields: [])
        }
        let (model, _) = await drafted(api)
        async let first: Void = model.apply()
        await Task.yield()
        async let second: Void = model.apply()
        _ = await (first, second)
        XCTAssertEqual(api.appliedPlans.count, 1)
    }

    func testNotConfiguredNamesTheSettings() async {
        let model = OnboardingPlanModel(apiProvider: { nil })
        model.transcript = "сон"
        await model.generate()
        XCTAssertEqual(model.draft, .failure(OnboardingMessages.notConfigured))
    }
}
