import SwiftUI

struct SettingsView: View {
    @State private var config = AIConfig(enabled: true, model: "gpt-4o-mini", temperature: 0.6, maxOutputTokens: 600)
    @AppStorage("az-dark-mode") private var darkMode = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Appearance") {
                    Toggle("Dark Mode", isOn: $darkMode)
                }

                Section("AI Metadata") {
                    Toggle("Enable AI Generation", isOn: $config.enabled)

                    Picker("Model", selection: $config.model) {
                        Text("gpt-4o-mini").tag("gpt-4o-mini")
                        Text("gpt-5-mini").tag("gpt-5-mini")
                    }

                    HStack {
                        Text("Temperature")
                        Spacer()
                        Text(String(format: "%.1f", config.temperature))
                            .font(.azMono)
                            .foregroundStyle(.secondary)
                    }
                    Slider(value: $config.temperature, in: 0...2, step: 0.1)

                    Stepper("Max Tokens: \(config.maxOutputTokens)", value: $config.maxOutputTokens, in: 16...4000, step: 50)
                }

                Section {
                    Button("Save Settings") {
                        // API call via ArtazzenAPI
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Color.azTeal)

                    Button("Reset to Defaults", role: .destructive) {
                        config = AIConfig(enabled: true, model: "gpt-4o-mini", temperature: 0.6, maxOutputTokens: 600)
                    }
                }

                Section("About") {
                    LabeledContent("Server", value: "artazzen.com")
                    LabeledContent("Version", value: "1.0.0")
                }
            }
            .navigationTitle("Settings")
        }
    }
}
