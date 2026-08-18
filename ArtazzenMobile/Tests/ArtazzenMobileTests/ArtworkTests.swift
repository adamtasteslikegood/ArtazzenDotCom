import XCTest
@testable import ArtazzenMobile

final class ArtworkTests: XCTestCase {
    let sampleJSON = """
    {
        "filename": "test.jpg",
        "title": "Test Artwork",
        "description": "A test description",
        "caption": "Test caption",
        "tags": ["abstract", "botanical"],
        "artist": "Test Artist",
        "copyright": "© 2026",
        "collection": "Test Collection",
        "status": "approved",
        "ai_generated": true,
        "ai_fields": ["title", "description"],
        "detected_at": 1718000000.0
    }
    """.data(using: .utf8)!

    func testDecode() throws {
        let artwork = try JSONDecoder().decode(Artwork.self, from: sampleJSON)
        XCTAssertEqual(artwork.filename, "test.jpg")
        XCTAssertEqual(artwork.title, "Test Artwork")
        XCTAssertEqual(artwork.caption, "Test caption")
        XCTAssertEqual(artwork.tags, ["abstract", "botanical"])
        XCTAssertEqual(artwork.artist, "Test Artist")
        XCTAssertEqual(artwork.copyright, "© 2026")
        XCTAssertEqual(artwork.collection, "Test Collection")
        XCTAssertEqual(artwork.status, .approved)
        XCTAssertTrue(artwork.aiGenerated)
        XCTAssertEqual(artwork.aiFields, [.title, .description])
        XCTAssertEqual(artwork.id, "test.jpg")
    }

    func testEncode() throws {
        let artwork = try JSONDecoder().decode(Artwork.self, from: sampleJSON)
        let encoded = try JSONEncoder().encode(artwork)
        let decoded = try JSONDecoder().decode(Artwork.self, from: encoded)
        XCTAssertEqual(artwork.filename, decoded.filename)
        XCTAssertEqual(artwork.tags, decoded.tags)
        XCTAssertEqual(artwork.aiFields, decoded.aiFields)
    }

    func testPendingStatus() throws {
        let json = """
        {
            "filename": "pending.jpg",
            "title": "",
            "description": "",
            "caption": "",
            "tags": [],
            "artist": "",
            "copyright": "",
            "collection": "",
            "status": "pending",
            "ai_generated": false,
            "ai_fields": [],
            "detected_at": 0
        }
        """.data(using: .utf8)!
        let artwork = try JSONDecoder().decode(Artwork.self, from: json)
        XCTAssertEqual(artwork.status, .pending)
        XCTAssertFalse(artwork.aiGenerated)
        XCTAssertTrue(artwork.aiFields.isEmpty)
    }
}
