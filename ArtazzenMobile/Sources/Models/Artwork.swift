import Foundation

struct Artwork: Codable, Identifiable, Hashable {
    var id: String { filename }
    let filename: String
    var title: String
    var description: String
    var caption: String
    var tags: [String]
    var artist: String
    var copyright: String
    var collection: String
    var status: ArtworkStatus
    var aiGenerated: Bool
    var aiFields: [AIField]
    let detectedAt: Double

    enum ArtworkStatus: String, Codable, CaseIterable {
        case pending, approved, hidden
    }

    enum AIField: String, Codable, CaseIterable {
        case title, caption, description, tags
    }

    var url: String?

    enum CodingKeys: String, CodingKey {
        case filename, title, description, caption, tags
        case artist, copyright, collection, status, url
        case aiGenerated = "ai_generated"
        case aiFields = "ai_fields"
        case detectedAt = "detected_at"
    }

    var imageURL: URL? {
        if let url, !url.isEmpty {
            return URL(string: url)
        }
        return nil
    }

    func imageURL(relativeTo base: URL) -> URL? {
        if let resolved = imageURL { return resolved }
        return base.appendingPathComponent("static/images/\(filename)")
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(filename)
    }

    static func == (lhs: Artwork, rhs: Artwork) -> Bool {
        lhs.filename == rhs.filename
    }
}
