// [review:need-review] PHASE-03/131
// summary: wire tests for POST /api/v1/health/samples — path, key header, snake_case body without an Idempotency-Key, decoded counts, a refused chunk as a typed error
import XCTest
@testable import HabitTracker

final class HealthAPIClientTests: XCTestCase {
    private var client: APIClient!

    override func setUp() {
        super.setUp()
        client = APIClient(
            baseURL: URL(string: "http://localhost:8873")!,
            apiKeyProvider: { "secret" },
            session: MockURLProtocol.makeSession()
        )
    }

    override func tearDown() {
        MockURLProtocol.requestHandler = nil
        client = nil
        super.tearDown()
    }

    private static let chunk = HealthSamplesRequestDTO(samples: [
        HealthSampleDTO(
            identifier: "HKQuantityTypeIdentifierStepCount", value: 1200, unit: "count",
            start: "2026-10-20T06:50:00.000Z", end: "2026-10-20T07:30:00.000Z",
            utcOffsetMinutes: 120
        ),
    ])

    private static func reply(_ request: URLRequest, status: Int, body: String) -> (HTTPURLResponse, Data) {
        let response = HTTPURLResponse(
            url: request.url!, statusCode: status, httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        )!
        return (response, Data(body.utf8))
    }

    func testChunkIsPostedAndTheServerCountsAreDecoded() async throws {
        var captured: URLRequest?
        MockURLProtocol.requestHandler = { request in
            captured = request
            return Self.reply(request, status: 200, body: #"{"samples_received": 1, "buckets_written": 2}"#)
        }

        let result = try await client.postHealthSamples(Self.chunk)

        XCTAssertEqual(result, HealthSamplesResponseDTO(samplesReceived: 1, bucketsWritten: 2))
        let request = try XCTUnwrap(captured)
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, "/api/v1/health/samples")
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-API-Key"), "secret")
        XCTAssertNil(request.value(forHTTPHeaderField: "Idempotency-Key"))
        let data = try XCTUnwrap(TodayScreenAPITests.bodyData(of: request))
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let samples = try XCTUnwrap(body["samples"] as? [[String: Any]])
        XCTAssertEqual(samples.first?["utc_offset_minutes"] as? Int, 120)
    }

    func testRefusedChunkSurfacesTheStatus() async {
        MockURLProtocol.requestHandler = { request in
            Self.reply(request, status: 422, body: #"{"detail": "unknown unit"}"#)
        }

        do {
            _ = try await client.postHealthSamples(Self.chunk)
            XCTFail("expected a refusal")
        } catch {
            XCTAssertEqual(error as? APIClientError, .unexpectedStatus(422))
        }
    }
}
