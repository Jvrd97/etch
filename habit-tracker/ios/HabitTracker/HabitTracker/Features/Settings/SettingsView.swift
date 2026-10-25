// [review:need-review] PHASE-01/32-ios-lime-tech-design-pass, PHASE-01/208, PHASE-01/214
// summary: Settings screen — Lime Tech dark restyle: card form rows, neon status indicator, lime accents; server address + API key + connection check + Face ID lock switches
import SwiftUI

struct SettingsView: View {
    @StateObject private var viewModel = SettingsViewModel()

    var body: some View {
        Form {
            Section("Server") {
                TextField("http://100.x.x.x:8000", text: $viewModel.serverAddress)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                SecureField("API key", text: $viewModel.apiKey)
            }
            .listRowBackground(DS.Palette.card)
            Section {
                Button {
                    Task { await viewModel.checkConnection() }
                } label: {
                    HStack {
                        Text("Check connection")
                            .foregroundStyle(DS.Palette.lime)
                        Spacer()
                        statusIndicator
                    }
                }
                .disabled(viewModel.connectionState == .checking)
            } footer: {
                if case .failure(let message) = viewModel.connectionState {
                    Text(message)
                        .foregroundStyle(DS.Palette.danger)
                }
            }
            .listRowBackground(DS.Palette.card)
            Section {
                Toggle("Face ID при входе", isOn: faceIDBinding)
                    .tint(DS.Palette.lime)
                if viewModel.faceIDLockEnabled {
                    Toggle("Код-пароль как запасной", isOn: passcodeBinding)
                        .tint(DS.Palette.lime)
                }
            } footer: {
                if let message = viewModel.lockMessage {
                    Text(message)
                        .foregroundStyle(DS.Palette.danger)
                } else {
                    Text("Ключ API открывается только после Face ID. Если набор Face ID изменится, введите ключ заново.")
                }
            }
            .listRowBackground(DS.Palette.card)
        }
        .navigationTitle("Settings")
        .dsScreenBackground()
    }

    private var faceIDBinding: Binding<Bool> {
        Binding(
            get: { viewModel.faceIDLockEnabled },
            set: { newValue in Task { await viewModel.setFaceIDLock(newValue) } }
        )
    }

    private var passcodeBinding: Binding<Bool> {
        Binding(
            get: { viewModel.passcodeFallbackEnabled },
            set: { newValue in Task { await viewModel.setPasscodeFallback(newValue) } }
        )
    }

    @ViewBuilder
    private var statusIndicator: some View {
        switch viewModel.connectionState {
        case .idle:
            EmptyView()
        case .checking:
            ProgressView()
                .tint(DS.Palette.lime)
        case .success:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(DS.Palette.success)
        case .failure:
            Image(systemName: "xmark.circle.fill")
                .foregroundStyle(DS.Palette.danger)
        }
    }
}
