// [review:need-review] PHASE-03/131, PHASE-03/132, PHASE-03/238
// summary: wire tests for POST /api/v1/health/samples — path, key header, snake_case body (samples and category_samples) without an Idempotency-Key, decoded counts, a refused chunk as a typed error, the sync-run keys of a chunk and the failure report by class
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

    func testChunkEncodesTheRunKeysTheServerJournalReads() async throws {
        var captured: URLRequest?
        MockURLProtocol.requestHandler = { request in
            captured = request
            return Self.reply(request, status: 200, body: #"{"samples_received": 1, "buckets_written": 1}"#)
        }
        var chunk = Self.chunk
        chunk.syncRunId = "3F6C1C52-0000-4000-8000-000000000001"
        chunk.kind = .backfill
        chunk.deviceId = "device-1"
        chunk.chunkIndex = 1
        chunk.chunksTotal = 3

        _ = try await client.postHealthSamples(chunk)

        let data = try XCTUnwrap(TodayScreenAPITests.bodyData(of: try XCTUnwrap(captured)))
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(body["sync_run_id"] as? String, "3F6C1C52-0000-4000-8000-000000000001")
        XCTAssertEqual(body["kind"] as? String, "backfill")
        XCTAssertEqual(body["device_id"] as? String, "device-1")
        XCTAssertEqual(body["chunk_index"] as? Int, 1)
        XCTAssertEqual(body["chunks_total"] as? Int, 3)
    }

    func testChunkWithoutRunKeysSendsOnlyTheTwoSampleLists() async throws {
        var captured: URLRequest?
        MockURLProtocol.requestHandler = { request in
            captured = request
            return Self.reply(request, status: 200, body: #"{"samples_received": 1, "buckets_written": 1}"#)
        }

        _ = try await client.postHealthSamples(Self.chunk)

        let data = try XCTUnwrap(TodayScreenAPITests.bodyData(of: try XCTUnwrap(captured)))
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        // `category_samples` goes as an empty list; the server defaults it the same way.
        XCTAssertEqual(Set(body.keys), ["samples", "category_samples"])
        XCTAssertEqual((body["category_samples"] as? [Any])?.count, 0)
    }

    func testFailureReportGoesToTheRunWithAClassAndNoMessage() async throws {
        var captured: URLRequest?
        MockURLProtocol.requestHandler = { request in
            captured = request
            return Self.reply(request, status: 200, body: #"{"status": "failed"}"#)
        }

        let ack = try await client.postHealthSyncFailure(
            runId: "RUN-1",
            HealthSyncFailureDTO(failureKind: .unknownMetric, kind: .manual, deviceId: "device-1", chunksTotal: 2)
        )

        XCTAssertEqual(ack, HealthSyncRunAckDTO(status: "failed"))
        let request = try XCTUnwrap(captured)
        XCTAssertEqual(request.url?.path, "/api/v1/health/sync-runs/RUN-1/fail")
        let data = try XCTUnwrap(TodayScreenAPITests.bodyData(of: request))
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(body["failure_kind"] as? String, "unknown_metric")
        XCTAssertEqual(Set(body.keys), ["failure_kind", "kind", "device_id", "chunks_total"])
    }
}
