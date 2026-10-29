// [review:need-review] PHASE-01/266
// summary: state of the Roles screen — the server's day (share per role, time blocks, acts) with the role directory through the read cache (offline answers carry their moment), the period summary read after it and kept apart so a failed summary never hides the day, the four writes of the web screen (minutes, act, confirm, remove) that need the network and re-read the day because one record moves every share, late answers dropped by a read counter; no note or title is ever logged
import Foundation

@MainActor
final class RolesViewModel: ObservableObject {
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    /// What the read cache keeps for the screen: the day and the directory for the pickers.
    struct Snapshot: Codable, Equatable {
        let day: RoleDayDTO
        let roles: [RoleDTO]
    }

    static let snapshotKey = "roles.day"

    static func summaryKey(_ period: RolesFormat.Period) -> String { "roles.summary.\(period.rawValue)" }

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var day: RoleDayDTO?
    @Published private(set) var roles: [RoleDTO] = []
    @Published private(set) var summary: RoleSummaryDTO?
    @Published private(set) var period: RolesFormat.Period = .week
    /// Non-nil while the screen shows cached answers because the server was out of reach.
    @Published private(set) var offlineAsOf: Date?
    @Published private(set) var isSaving = false
    /// Why the last write or refresh was refused, in words; the screen keeps what it had.
    @Published var errorMessage: String?

    private let apiProvider: () -> RolesAPI?
    private let cache: ReadThroughCache
    private var generation = 0
    private var summaryGeneration = 0

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

    static func live() -> RolesViewModel {
        RolesViewModel(apiProvider: { APIClient.live() }, cacheStore: ReadCacheLive.shared)
    }

    // MARK: Reading

    func load() async {
        await read(silent: false)
    }

    /// The screen came on again: with an answer already shown it is read in place.
    func appear() async {
        await read(silent: day != nil)
    }

    func refresh() async {
        await read(silent: true)
    }

    func select(period newPeriod: RolesFormat.Period) async {
        guard newPeriod != period else { return }
        period = newPeriod
        summary = nil
        await readSummary()
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
                async let today = api.fetchRoleDay()
                async let directory = api.fetchRoles()
                return try await Snapshot(day: today, roles: directory)
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
            return
        }
        await readSummary()
    }

    private func show(_ snapshot: Snapshot) {
        day = snapshot.day
        roles = snapshot.roles
    }

    /// The summary is a second block of the screen: when it cannot be read the block is absent, as on the web.
    private func readSummary() async {
        guard let api = apiProvider(), let lastDay = day?.workDay,
              let bounds = RolesFormat.range(endingOn: lastDay, period: period)
        else { return }
        summaryGeneration += 1
        let mine = summaryGeneration
        let asked = period
        do {
            let outcome = try await cache.load(key: Self.summaryKey(asked)) {
                try await api.fetchRoleSummary(dateFrom: bounds.from, dateTo: bounds.to)
            }
            guard mine == summaryGeneration, asked == period else { return }
            switch outcome {
            case .fresh(let value), .stale(let value, _): summary = value
            }
        } catch {
            guard mine == summaryGeneration, asked == period else { return }
            summary = nil
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

    /// Minutes by hand. Returns whether the server took it, so the form knows to clear itself.
    @discardableResult
    func addMinutes(roleCode: String, minutes: Int, note: String) async -> Bool {
        guard minutes > 0 else {
            errorMessage = "Минут должно быть больше нуля"
            return false
        }
        guard let workDay = day?.workDay else { return false }
        let trimmed = note.trimmingCharacters(in: .whitespacesAndNewlines)
        return await write { api in
            _ = try await api.addRoleTimeBlock(
                RoleTimeBlockDraftDTO(
                    roleCode: roleCode, minutes: minutes, workDay: workDay, note: trimmed.isEmpty ? nil : trimmed
                )
            )
        }
    }

    @discardableResult
    func addAct(roleCode: String, actKind: String, title: String) async -> Bool {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let workDay = day?.workDay else { return false }
        return await write { api in
            _ = try await api.addRoleAct(
                RoleActDraftDTO(roleCode: roleCode, actKind: actKind, title: trimmed, workDay: workDay)
            )
        }
    }

    func removeBlock(id: Int) async {
        await write { api in try await api.deleteRoleTimeBlock(id: id) }
    }

    /// «Посчитано верно»: from now on the markup leaves the record alone.
    func confirmBlock(id: Int) async {
        await write { api in _ = try await api.confirmRoleTimeBlock(id: id) }
    }

    @discardableResult
    private func write(_ send: (RolesAPI) async throws -> Void) async -> Bool {
        guard !isSaving else { return false }
        guard let api = apiProvider() else {
            errorMessage = RolesFormat.notConfiguredMessage
            return false
        }
        isSaving = true
        errorMessage = nil
        defer { isSaving = false }
        do {
            try await send(api)
        } catch {
            errorMessage = writeFailedMessage(error)
            return false
        }
        await read(silent: true)
        return true
    }

    private func writeFailedMessage(_ error: Error) -> String {
        if let error = error as? APIClientError, error.isConnectivity {
            return "Нет связи: запись ролей уходит только при сети, повторите позже"
        }
        return RolesFormat.message(for: error)
    }
}
