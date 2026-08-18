import Foundation

struct AIConfig: Codable {
    var enabled: Bool
    var model: String
    var temperature: Double
    var maxOutputTokens: Int

    enum CodingKeys: String, CodingKey {
        case enabled, model, temperature
        case maxOutputTokens = "max_output_tokens"
    }
}

struct AIConfigResponse: Codable {
    let ai: AIConfig
}
