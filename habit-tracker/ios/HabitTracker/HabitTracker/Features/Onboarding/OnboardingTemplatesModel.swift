// [review:need-review] PHASE-01/267
// summary: the templates step of the onboarding — the built-in catalog through the read cache (offline shows the last catalog with its moment), a pick that never applies on its own, an apply that names what was added and what was skipped because the category exists, a step the person can dismiss and bring back
import Foundation

@MainActor
final class OnboardingTemplatesModel: ObservableObject {
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    enum Step: Equatable {
        case open
        case dismissed
        case applied(added: [String], skipped: [String])
    }

    static let cacheKey = "onboarding.templates"

    @Published private(set) var loadState: LoadState = .idle
    @Published private(set) var templates: [CategoryTemplateDTO] = []
    @Published private(set) var selected: Set<String> = []
    @Published private(set) var step: Step = .open
    @Published private(set) var isApplying = false
    /// Why the last apply failed; the pick stays so a retry is one tap.
    @Published private(set) var applyError: String?
    /// Set while the catalog is a cached one: when it was fetched.
    @Published private(set) var offlineAsOf: Date?

    private let apiProvider: () -> OnboardingAPI?
    private let cache: ReadThroughCache
    private var generation = 0

    init(apiProvider: @escaping () -> OnboardingAPI?, cacheStore: CacheStore, now: @escaping () -> Date = Date.init) {
        self.apiProvider = apiProvider
        self.cache = ReadThroughCache(store: cacheStore, now: now)
    }

    convenience init(api: OnboardingAPI, cacheStore: CacheStore, now: @escaping () -> Date = Date.init) {
        self.init(apiProvider: { api }, cacheStore: cacheStore, now: now)
    }

    static func live() -> OnboardingTemplatesModel {
        OnboardingTemplatesModel(apiProvider: { APIClient.live() }, cacheStore: ReadCacheLive.shared)
    }

    /// Nothing to apply until something is ticked, and nothing while an apply is in flight.
    var canApply: Bool { !selected.isEmpty && !isApplying }

    func load() async {
        generation += 1
        let mine = generation
        loadState = .loading
        guard let api = apiProvider() else {
            loadState = .failure(OnboardingMessages.notConfigured)
            return
        }
        do {
            let outcome = try await cache.load(key: Self.cacheKey) { try await api.fetchTemplates() }
            guard mine == generation else { return }
            switch outcome {
            case .fresh(let items):
                templates = items
                offlineAsOf = nil
            case .stale(let items, let updatedAt):
                templates = items
                offlineAsOf = updatedAt
            }
            // A key that a fresh catalog marks as added cannot stay ticked.
            selected = selected.filter { key in templates.contains { $0.key == key && !$0.added } }
            loadState = .loaded
        } catch let error as APIClientError {
            guard mine == generation else { return }
            loadState = .failure(OnboardingMessages.base(error))
        } catch {
            guard mine == generation else { return }
            loadState = .failure(OnboardingMessages.templatesFailed)
        }
    }

    func toggle(_ key: String) {
        guard let template = templates.first(where: { $0.key == key }), !template.added else { return }
        if selected.contains(key) { selected.remove(key) } else { selected.insert(key) }
    }

    func dismiss() { step = .dismissed }

    /// Brings the picker back and reads the catalog again: what was added meanwhile is marked.
    func reopen() async {
        step = .open
        await load()
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
        // The catalog the person saw names the skipped keys; keep it before the answer.
        let shown = templates
        let keys = shown.map(\.key).filter(selected.contains)
        do {
            let result = try await api.applyTemplates(keys: keys)
            step = .applied(
                added: result.categories.map(\.name),
                skipped: result.skipped.map { key in shown.first { $0.key == key }?.name ?? key }
            )
            selected = []
        } catch let error as APIClientError {
            applyError = OnboardingMessages.base(error)
        } catch {
            applyError = OnboardingMessages.templatesApplyFailed
        }
    }

    func dismissApplyError() { applyError = nil }
}
