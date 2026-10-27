// [review:need-review] PHASE-03/240
// summary: wire tests of the supplement endpoints against the server's schemas (#223) — the list decodes with taken_today and a time of day, the create answer without taken_today reads as not taken, the create body, the intake POST under its Idempotency-Key with an empty body for a direct press and the day as a clock check for a replay, and 409/404 as statuses
import XCTest
@testable import HabitTracker

final class SupplementsAPIClientTests: XCTestCase {
    private var client: APIClient!
    private var captured: URLRequest?
    private var capturedBody: Data?

    override func setUp() {
        super.setUp()
        client = APIClient(
            baseURL: URL(string: "http://localhost:8840")!,
            apiKeyProvider: { "secret" },
            session: MockURLProtocol.makeSession()
        )
        captured = nil
        capturedBody = nil
    }

    override func tearDown() {
        MockURLProtocol.requestHandler = nil
        client = nil
        super.tearDown()
    }

    private func respond(_ body: String, status: Int = 200) {
        MockURLProtocol.requestHandler = { [unowned self] request in
            self.captured = request
            self.capturedBody = request.httpBody ?? request.httpBodyStream.map { stream in
                stream.open()
                defer { stream.close() }
                var data = Data()
                var buffer = [UInt8](repeating: 0, count: 1024)
                while stream.hasBytesAvailable {
                    let count = stream.read(&buffer, maxLength: buffer.count)
                    if count <= 0 { break }
                    data.append(buffer, count: count)
                }
                return data
            }
            let response = HTTPURLResponse(
                url: request.url!, statusCode: status, httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(body.utf8))
        }
    }

    private static let listBody = """
    [
      {"id": 1, "name": "Магний", "dose": 400.0, "unit": "мг", "intake_time": "21:30:00",
       "is_active": true, "created_at": "2026-10-26T08:00:00Z", "archived_at": null, "taken_today": true},
      {"id": 2, "name": "Омега-3", "dose": 0.5, "unit": "г", "intake_time": null,
       "is_active": true, "created_at": "2026-10-26T08:05:00Z", "archived_at": null, "taken_today": false}
    ]
    """

    func testListDecodesTakenTodayAndTimeOfDay() async throws {
        respond(Self.listBody)

        let list = try await client.fetchSupplements()

        XCTAssertEqual(captured?.url?.path, "/api/v1/supplements")
        XCTAssertEqual(captured?.httpMethod, "GET")
        XCTAssertEqual(captured?.value(forHTTPHeaderField: "X-API-Key"), "secret")
        XCTAssertEqual(list.map(\.name), ["Магний", "Омега-3"])
        XCTAssertEqual(list[0].intakeTime, "21:30:00")
        XCTAssertTrue(list[0].takenToday)
        XCTAssertNil(list[1].intakeTime)
        XCTAssertFalse(list[1].takenToday)
    }

    func testCreateAnswerWithoutTakenTodayReadsAsNotTaken() async throws {
        respond("""
        {"id": 3, "name": "D3", "dose": 2000.0, "unit": "МЕ", "intake_time": "08:00:00",
         "is_active": true, "created_at": "2026-10-27T08:00:00Z", "archived_at": null}
        """, status: 201)

        let created = try await client.createSupplement(
            SupplementCreateDTO(name: "D3", dose: 2000, unit: "МЕ", intakeTime: "08:00:00")
        )

        XCTAssertEqual(captured?.httpMethod, "POST")
        XCTAssertEqual(captured?.url?.path, "/api/v1/supplements")
        XCTAssertEqual(created.id, 3)
        XCTAssertFalse(created.takenToday)
        let body = try XCTUnwrap(capturedBody.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] })
        XCTAssertEqual(body["name"] as? String, "D3")
        XCTAssertEqual(body["dose"] as? Double, 2000)
        XCTAssertEqual(body["unit"] as? String, "МЕ")
        XCTAssertEqual(body["intake_time"] as? String, "08:00:00")
    }

    func testCreateWithoutTimeLeavesTheKeyOut() async throws {
        respond("""
        {"id": 4, "name": "C", "dose": 500.0, "unit": "мг", "intake_time": null,
         "is_active": true, "created_at": "2026-10-27T08:00:00Z", "archived_at": null}
        """, status: 201)

        _ = try await client.createSupplement(SupplementCreateDTO(name: "C", dose: 500, unit: "мг", intakeTime: nil))

        let body = try XCTUnwrap(capturedBody.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] })
        XCTAssertNil(body["intake_time"])
    }

    func testDirectPressSendsTheKeyAndNoDay() async throws {
        respond(#"{"id": 9, "supplement_id": 2, "intake_date": "2026-10-27", "taken_at": "2026-10-27T08:00:00Z"}"#, status: 201)

        let intake = try await client.markIntake(supplementID: 2, intakeDate: nil, idempotencyKey: "key-1")

        XCTAssertEqual(captured?.url?.path, "/api/v1/supplements/2/intakes")
        XCTAssertEqual(captured?.httpMethod, "POST")
        XCTAssertEqual(captured?.value(forHTTPHeaderField: "Idempotency-Key"), "key-1")
        XCTAssertEqual(intake.supplementId, 2)
        XCTAssertEqual(intake.intakeDate, "2026-10-27")
        let body = try XCTUnwrap(capturedBody.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] })
        XCTAssertTrue(body.isEmpty, "the server decides the day")
    }

    func testReplayCarriesTheDayOfThePressAsAClockCheck() async throws {
        respond(#"{"id": 9, "supplement_id": 2, "intake_date": "2026-10-26", "taken_at": "2026-10-26T20:00:00Z"}"#, status: 200)

        _ = try await client.markIntake(supplementID: 2, intakeDate: "2026-10-26", idempotencyKey: "key-2")

        let body = try XCTUnwrap(capturedBody.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] })
        XCTAssertEqual(body["intake_date"] as? String, "2026-10-26")
    }

    func testRefusalsComeAsStatuses() async {
        for status in [404, 409] {
            respond(#"{"detail": "no"}"#, status: status)
            do {
                _ = try await client.markIntake(supplementID: 2, intakeDate: nil, idempotencyKey: "k")
                XCTFail("expected \(status)")
            } catch {
                XCTAssertEqual(error as? APIClientError, .unexpectedStatus(status))
            }
        }
    }
}
