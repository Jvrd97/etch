// [review:need-review] PHASE-01/267
// summary: the first-launch entry into the onboarding — once, when the server answers with no categories at all, the onboarding opens as a sheet; a failed read opens nothing and marks nothing, categories already there or a closed sheet mark the offer as made; RootView carries one modifier
import SwiftUI
import os

/// Remembers that the onboarding was offered, so a person who deletes every category later is not nagged.
protocol OnboardingOfferStore {
    var wasOffered: Bool { get }
    func markOffered()
}

struct UserDefaultsOnboardingOfferStore: OnboardingOfferStore {
    static let key = "habit-tracker:onboarding-offered"
    let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    var wasOffered: Bool { defaults.bool(forKey: Self.key) }
    func markOffered() { defaults.set(true, forKey: Self.key) }
}

@MainActor
final class OnboardingGateModel: ObservableObject {
    @Published var isPresented = false

    private let apiProvider: () -> OnboardingAPI?
    private let store: OnboardingOfferStore
    private static let logger = Logger(subsystem: "com.habittracker.app", category: "OnboardingGate")

    init(apiProvider: @escaping () -> OnboardingAPI?, store: OnboardingOfferStore) {
        self.apiProvider = apiProvider
        self.store = store
    }

    static func live() -> OnboardingGateModel {
        OnboardingGateModel(apiProvider: { APIClient.live() }, store: UserDefaultsOnboardingOfferStore())
    }

    /// Asks the server once per install. No server address, no answer or an error: stay quiet and ask next launch.
    func check() async {
        guard !store.wasOffered, let api = apiProvider() else { return }
        do {
            let categories = try await api.fetchCategories()
            if categories.isEmpty {
                isPresented = true
            } else {
                store.markOffered()
            }
        } catch {
            Self.logger.info("First-launch category check failed: \(String(describing: error))")
        }
    }

    /// The sheet went away, by Close or after the plan was applied: either way it has been offered.
    func finish() {
        isPresented = false
        store.markOffered()
    }
}

private struct OnboardingGateModifier: ViewModifier {
    @StateObject private var gate = OnboardingGateModel.live()
    let openCategories: () -> Void

    func body(content: Content) -> some View {
        content
            .task { await gate.check() }
            .sheet(isPresented: $gate.isPresented, onDismiss: { gate.finish() }) {
                NavigationStack {
                    OnboardingView(onOpenCategories: {
                        gate.finish()
                        openCategories()
                    })
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("Закрыть") { gate.finish() }
                        }
                    }
                }
                .preferredColorScheme(.dark)
            }
    }
}

extension View {
    /// Offers the onboarding on the first launch with an empty category list.
    func onboardingGate(openCategories: @escaping () -> Void) -> some View {
        modifier(OnboardingGateModifier(openCategories: openCategories))
    }
}
