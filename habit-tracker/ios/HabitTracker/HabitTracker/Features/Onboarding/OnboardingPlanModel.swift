// [review:need-review] PHASE-01/267
// summary: the voice-category-builder step of the onboarding — the words of the person, a plan drafted by the model (a fake in tests, never a real one), per-operation opt-in with editable names (a new category without a name clash starts on, a field added to an existing category or a clashing name starts off), and the ticked part applied as one batch; words of 503/502/400/422 in plain language
import Foundation

@MainActor
final class OnboardingPlanModel: ObservableObject {
    enum DraftState: Equatable {
        case idle
        case loading
        case failure(String)
        case done(OnboardingPlanDTO)
    }

    struct OpState: Equatable {
        var enabled: Bool
        var name: String
    }

    /// The model is called synchronously on the server: a generous timeout.
    static let draftTimeout: TimeInterval = 120

    @Published var transcript = ""
    @Published private(set) var draft: DraftState = .idle
    @Published private(set) var opStates: [OpState] = []
    @Published private(set) var isApplying = false
    @Published private(set) var applyError: String?
    /// The last apply went through; the screen then opens Categories.
    @Published private(set) var didApply = false

    private let apiProvider: () -> OnboardingAPI?
    private var generation = 0

    init(apiProvider: @escaping () -> OnboardingAPI?) {
        self.apiProvider = apiProvider
    }

    convenience init(api: OnboardingAPI) {
        self.init(apiProvider: { api })
    }

    static func live() -> OnboardingPlanModel {
        OnboardingPlanModel(apiProvider: { APIClient.live(timeout: draftTimeout) })
    }

    var operations: [OnboardingOperationDTO] {
        if case .done(let plan) = draft { return plan.operations }
        return []
    }

    var enabledCount: Int { opStates.filter(\.enabled).count }

    var canGenerate: Bool {
        !transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && draft != .loading
    }

    /// A ticked new category needs a name; the server refuses an empty one.
    var canApply: Bool {
        guard enabledCount > 0, !isApplying else { return false }
        return zip(operations, opStates).allSatisfy { op, state in
            guard state.enabled, case .createCategory = op else { return true }
            return !state.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }

    static func initialStates(_ plan: OnboardingPlanDTO) -> [OpState] {
        plan.operations.map { op in
            switch op {
            case .createCategory(let create): return OpState(enabled: !create.nameConflict, name: create.name)
            case .addField: return OpState(enabled: false, name: "")
            }
        }
    }

    /// The batch payload: the operations left on, a new category carrying its edited name.
    func selectedOperations() -> [OnboardingOperationDTO] {
        var selected: [OnboardingOperationDTO] = []
        for (op, state) in zip(operations, opStates) where state.enabled {
            switch op {
            case .createCategory(var create):
                create.name = state.name.trimmingCharacters(in: .whitespacesAndNewlines)
                selected.append(.createCategory(create))
            case .addField:
                selected.append(op)
            }
        }
        return selected
    }

    func generate() async {
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, draft != .loading else { return }
        generation += 1
        let mine = generation
        draft = .loading
        // A new plan retires what the last one failed to apply: the old banner would blame the new preview.
        applyError = nil
        didApply = false
        guard let api = apiProvider() else {
            draft = .failure(OnboardingMessages.notConfigured)
            return
        }
        do {
            let plan = try await api.draftPlan(transcript: text)
            guard mine == generation else { return }
            opStates = Self.initialStates(plan)
            draft = .done(plan)
        } catch let error as APIClientError {
            guard mine == generation else { return }
            draft = .failure(OnboardingMessages.draft(error))
        } catch {
            guard mine == generation else { return }
            draft = .failure(OnboardingMessages.draftFailed)
        }
    }

    func setEnabled(_ index: Int, _ enabled: Bool) {
        guard opStates.indices.contains(index) else { return }
        opStates[index].enabled = enabled
    }

    func setName(_ index: Int, _ name: String) {
        guard opStates.indices.contains(index) else { return }
        opStates[index].name = name
    }

    func apply() async {
        guard canApply else { return }
        guard let api = apiProvider() else {
            applyError = OnboardingMessages.notConfigured
            return
        }
        isApplying = true
        applyError = nil
        defer { isApplying = false }
        do {
            _ = try await api.applyPlan(selectedOperations())
            didApply = true
        } catch let error as APIClientError {
            applyError = OnboardingMessages.planApply(error)
        } catch {
            applyError = OnboardingMessages.planApplyFailed
        }
    }
}
