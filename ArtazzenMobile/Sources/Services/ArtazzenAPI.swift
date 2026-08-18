import Foundation

actor ArtazzenAPI {
    let baseURL: URL
    private let credentials: (username: String, password: String)

    init(baseURL: URL, username: String, password: String) {
        self.baseURL = baseURL
        self.credentials = (username, password)
    }

    private func authHeader() -> String {
        let encoded = Data("\(credentials.username):\(credentials.password)".utf8).base64EncodedString()
        return "Basic \(encoded)"
    }

    private func request(_ path: String, method: String = "GET", body: Data? = nil) async throws -> Data {
        var req = URLRequest(url: baseURL.appendingPathComponent(path))
        req.httpMethod = method
        req.setValue(authHeader(), forHTTPHeaderField: "Authorization")
        if let body {
            req.httpBody = body
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            throw APIError.requestFailed
        }
        return data
    }

    struct PendingResponse: Codable {
        let pending: [ArtworkWrapper]
        let gallery: [ArtworkWrapper]
    }

    struct ArtworkWrapper: Codable {
        let name: String
        let url: String
        let title: String?
        let metadata: Artwork?
    }

    func fetchFiles() async throws -> PendingResponse {
        let data = try await request("/admin/api/new-files")
        return try JSONDecoder().decode(PendingResponse.self, from: data)
    }

    func saveMetadata(_ artwork: Artwork) async throws {
        var components = URLComponents()
        components.queryItems = [
            URLQueryItem(name: "title", value: artwork.title),
            URLQueryItem(name: "description", value: artwork.description),
            URLQueryItem(name: "caption", value: artwork.caption),
            URLQueryItem(name: "tags", value: artwork.tags.joined(separator: ", ")),
            URLQueryItem(name: "artist", value: artwork.artist),
            URLQueryItem(name: "copyright", value: artwork.copyright),
            URLQueryItem(name: "collection", value: artwork.collection),
            URLQueryItem(name: "action", value: "save"),
        ]
        let body = components.percentEncodedQuery?.data(using: .utf8)
        var req = URLRequest(url: baseURL.appendingPathComponent("/admin/metadata/\(artwork.filename)"))
        req.httpMethod = "POST"
        req.setValue(authHeader(), forHTTPHeaderField: "Authorization")
        req.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        let (_, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse, 200..<400 ~= http.statusCode else {
            throw APIError.requestFailed
        }
    }

    struct RegenRequest: Codable {
        let images: [String]
        let fields: [String]?
        let force: Bool
    }

    struct RegenResponse: Codable {
        struct Updated: Codable {
            let name: String
            let metadata: Artwork
        }
        let updated: [Updated]
        let errors: [[String: String]]
    }

    func regenerateFields(image: String, fields: [Artwork.AIField], force: Bool = true) async throws -> Artwork? {
        let body = try JSONEncoder().encode(RegenRequest(
            images: [image],
            fields: fields.map(\.rawValue),
            force: force
        ))
        let data = try await request("/admin/ai/regenerate", method: "POST", body: body)
        let response = try JSONDecoder().decode(RegenResponse.self, from: data)
        return response.updated.first?.metadata
    }

    func upload(imageData: Data, filename: String) async throws {
        let boundary = UUID().uuidString
        var req = URLRequest(url: baseURL.appendingPathComponent("/admin/upload"))
        req.httpMethod = "POST"
        req.setValue(authHeader(), forHTTPHeaderField: "Authorization")
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"files\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: image/jpeg\r\n\r\n".data(using: .utf8)!)
        body.append(imageData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        req.httpBody = body

        let (_, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            throw APIError.requestFailed
        }
    }

    func unapprove(_ name: String) async throws {
        _ = try await request("/admin/unapprove/\(name)", method: "POST")
    }

    func delete(_ name: String) async throws {
        _ = try await request("/admin/delete/\(name)", method: "POST")
    }

    func fetchCollections() async throws -> [String] {
        struct Response: Codable { let collections: [String] }
        let data = try await request("/admin/api/collections")
        return try JSONDecoder().decode(Response.self, from: data).collections
    }

    func fetchConfig() async throws -> AIConfig {
        let data = try await request("/admin/config")
        return try JSONDecoder().decode(AIConfigResponse.self, from: data).ai
    }

    enum APIError: Error {
        case requestFailed
    }
}
