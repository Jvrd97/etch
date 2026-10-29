// [review:need-review] PHASE-01/266
// summary: state of the markup-rules screen — rules in the order the resolver picks a winner (smaller priority, then smaller id), the directory for the form, the server's day for the bounds, all through the read cache; a new rule with its dry run over the history (nothing is saved by a dry run), a rule switched off and on (the server has no delete: a switched-off rule is the way to remove one), and the re-markup of a period with its before/after; writes need the network; patterns are never logged
import Foundation

@MainActor
final class RoleRulesViewModel: ObservableObject {
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    struct Snapshot: Codable, Equatable {
        let rules: [RoleRuleDTO]
        let roles: [RoleDTO]
        let today: String
    }

    struct Draft: Equatable {
        var roleCode = ""
        var source = RolesFormat.sources[0].id
        var matcherKind = RolesFormat.matchers[0].id
        var pattern = ""
        var priority = RolesFormat.defaultPriority
    }

    static let snapshotKey = "roles.rules"
    @Published private(set) var state: LoadState = .idle
    @Published private(set) var rules: [RoleRuleDTO] = []
    @Published private(set) var roles: [RoleDTO] = []
    @Published private(set) var today: String?
    @Published private(set) var offlineAsOf: Date?
    @Published var draft = Draft()
    @Published private(set) var dryRun: RoleRuleDryRunDTO?
    @Published private(set) var reclassified: RoleReclassifiedDTO?
    /// The bounds of the re-markup, any two days; `nil` until the server's day is known.
    @Published var reclassifyFrom: Date?
    @Published var reclassifyTo: Date?
    @Published private(set) var isBusy = false
    @Published var errorMessage: String?

    private let apiProvider: () -> RolesAPI?
    private let cache: ReadThroughCache
    private var generation = 0

    init(
        apiProvider: @escaping () -> RolesAPI?,
        cacheStore: CacheStore = InMemoryCacheStore(),
        now: @escaping () -> Date = Date.init
    ) {
        self.apiProvider = apiProvider
        self.cache = ReadThroughCache(store: cacheStore, now: now)
    }

    convenience init(api: RolesAPI, cacheStore: CacheStore = InMemoryCacheStore()) {
        self.init(apiProvider: { api }, cacheStore: cacheStore)
    }

    static func live() -> RoleRulesViewModel {
        RoleRulesViewModel(apiProvider: { APIClient.live() }, cacheStore: ReadCacheLive.shared)
    }

    var canSubmitDraft: Bool {
        !draft.pattern.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !draft.roleCode.isEmpty && !isBusy
    }

    // MARK: Reading

    func load() async {
        await read(silent: false)
    }

    func appear() async {
        await read(silent: state == .loaded)
    }

    func refresh() async {
        await read(silent: true)
    }

    private func read(silent: Bool) async {
        generation += 1
        let mine = generation
        if !silent { state = .loading }
        guard let api = apiProvider() else {
            fail(RolesFormat.notConfiguredMessage, silent: silent)
            return
        }
        do {
            let outcome = try await cache.load(key: Self.snapshotKey) {
                async let markup = api.fetchRoleRules()
                async let directory = api.fetchRoles()
                async let day = api.fetchRoleDay()
                return try await Snapshot(rules: markup, roles: directory, today: day.workDay)
            }
            guard mine == generation else { return }
            switch outcome {
            case .fresh(let snapshot):
                offlineAsOf = nil
                show(snapshot)
            case .stale(let snapshot, let updatedAt):
                offlineAsOf = updatedAt
                show(snapshot)
            }
            errorMessage = nil
            state = .loaded
        } catch {
            guard mine == generation else { return }
            fail(RolesFormat.message(for: error), silent: silent)
        }
    }

    private func show(_ snapshot: Snapshot) {
        rules = snapshot.rules
        roles = snapshot.roles
        today = snapshot.today
        if reclassifyFrom == nil || reclassifyTo == nil { selectReclassify(period: .month) }
        if draft.roleCode.isEmpty || !snapshot.roles.contains(where: { $0.code == draft.roleCode }) {
            draft.roleCode = snapshot.roles.first?.code ?? ""
        }
    }

    private func fail(_ message: String, silent: Bool) {
        if silent {
            errorMessage = message
        } else {
            state = .failure(message)
        }
    }

    // MARK: Writing

    private var draftDTO: RoleRuleDraftDTO {
        RoleRuleDraftDTO(
            roleCode: draft.roleCode, source: draft.source, matcherKind: draft.matcherKind,
            pattern: draft.pattern.trimmingCharacters(in: .whitespacesAndNewlines), priority: draft.priority
        )
    }

    /// Runs the draft over the last 30 days of markup and shows how many rows it would catch. Saves nothing.
    func runDryRun() async {
        guard canSubmitDraft, let api = prepared() else { return }
        await perform {
            self.dryRun = try await api.dryRunRoleRule(self.draftDTO)
        }
    }

    func saveRule() async {
        guard canSubmitDraft, let api = prepared() else { return }
        let saved = await perform {
            _ = try await api.addRoleRule(self.draftDTO)
        }
        guard saved else { return }
        dryRun = nil
        draft.pattern = ""
        await read(silent: true)
    }

    /// The server has no delete for a rule: switched off, it no longer takes part in the markup.
    func setActive(_ rule: RoleRuleDTO, isActive: Bool) async {
        guard let api = prepared() else { return }
        let saved = await perform {
            _ = try await api.setRoleRuleActive(id: rule.id, isActive: isActive)
        }
        if saved { await read(silent: true) }
    }

    /// A ready-made span ending on the server's day: sets both dates, which stay editable.
    func selectReclassify(period: RolesFormat.Period) {
        guard let today, let bounds = RolesFormat.range(endingOn: today, period: period) else { return }
        reclassifyFrom = RolesFormat.date(fromDay: bounds.from)
        reclassifyTo = RolesFormat.date(fromDay: bounds.to)
    }

    var canReclassify: Bool {
        guard let from = reclassifyFrom, let to = reclassifyTo else { return false }
        return from <= to && !isBusy
    }

    func reclassify() async {
        guard canReclassify, let from = reclassifyFrom, let to = reclassifyTo, let api = prepared() else { return }
        let dateFrom = RolesFormat.dayString(from)
        let dateTo = RolesFormat.dayString(to)
        await perform {
            self.reclassified = try await api.reclassifyRoles(dateFrom: dateFrom, dateTo: dateTo)
        }
    }

    private func prepared() -> RolesAPI? {
        guard !isBusy else { return nil }
        guard let api = apiProvider() else {
            errorMessage = RolesFormat.notConfiguredMessage
            return nil
        }
        return api
    }

    @discardableResult
    private func perform(_ work: () async throws -> Void) async -> Bool {
        isBusy = true
        errorMessage = nil
        defer { isBusy = false }
        do {
            try await work()
            return true
        } catch {
            if let error = error as? APIClientError, error.isConnectivity {
                errorMessage = "Нет связи: правила меняются только при сети, повторите позже"
            } else {
                errorMessage = RolesFormat.message(for: error)
            }
            return false
        }
    }
}
