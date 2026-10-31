// [review:need-review] PHASE-01/216, PHASE-03/295
// summary: wire tests of the goal endpoints against the server's schemas — GET /goals decodes levels, milestones with their dependency codes and «in-progress», the quarter and its goals; PATCH /goals/milestones/{code} sends the status alone; 404 arrives as a status; PUT /goals/quarter/{quarter} sends the whole set in snake_case, 422 carries the server's Russian reason, a non-string detail and 401 stay plain statuses
import XCTest
@testable import HabitTracker

final class GoalsAPIClientTests: XCTestCase {
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

    func testBoardDecodesLevelsMilestonesAndQuarter() async throws {
        respond("""
        {
          "levels": [{"level": 0, "title": "Миссия", "body_md": "**Небольшой дом**",
                      "open_questions": ["⚠ подтверди: какой из двух главный"]}],
          "milestones": [
            {"code": "M9", "title": "Девятый", "done_criterion": null, "when_text": "Q4",
             "ord": 9, "status": "in-progress", "done_on": null, "depends_on": []},
            {"code": "M10", "title": "Десятый", "done_criterion": "релиз", "when_text": null,
             "ord": 10, "status": "done", "done_on": "2026-08-30", "depends_on": ["M8", "M9"]}
          ],
          "quarter": "2026-Q4",
          "goals": [{"id": 7, "quarter": "2026-Q4", "ord": 1, "text_md": "**Цель**",
                     "milestone_code": "M9", "status": "open"}]
        }
        """)

        let board = try await client.fetchGoals()

        XCTAssertEqual(captured?.url?.path, "/api/v1/goals")
        XCTAssertEqual(captured?.httpMethod, "GET")
        XCTAssertEqual(captured?.value(forHTTPHeaderField: "X-API-Key"), "secret")
        XCTAssertEqual(board.levels.first?.openQuestions, ["⚠ подтверди: какой из двух главный"])
        XCTAssertEqual(board.levels.first?.bodyMd, "**Небольшой дом**")
        XCTAssertEqual(board.milestones.map(\.status), [.inProgress, .done])
        XCTAssertEqual(board.milestones[1].dependsOn, ["M8", "M9"])
        XCTAssertEqual(board.milestones[1].doneOn, "2026-08-30")
        XCTAssertNil(board.milestones[0].doneCriterion)
        XCTAssertEqual(board.quarter, "2026-Q4")
        XCTAssertEqual(board.goals.first?.milestoneCode, "M9")
    }

    func testPatchMilestoneSendsStatusOnly() async throws {
        respond("""
        {"code": "M9", "title": "Девятый", "done_criterion": null, "when_text": null,
         "ord": 9, "status": "done", "done_on": "2026-10-29", "depends_on": []}
        """)

        let milestone = try await client.patchMilestone(code: "M9", status: .done)

        XCTAssertEqual(captured?.url?.path, "/api/v1/goals/milestones/M9")
        XCTAssertEqual(captured?.httpMethod, "PATCH")
        let body = try XCTUnwrap(capturedBody)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: String])
        XCTAssertEqual(json, ["status": "done"])
        XCTAssertEqual(milestone.doneOn, "2026-10-29")
    }

    func testPatchOfUnknownMilestoneIsAStatus() async {
        respond(#"{"detail": "Милстона M99 нет."}"#, status: 404)

        do {
            _ = try await client.patchMilestone(code: "M99", status: .open)
            XCTFail("expected 404")
        } catch {
            XCTAssertEqual(error as? APIClientError, .unexpectedStatus(404))
        }
    }

    func testPutQuarterSendsTheWholeSetInSnakeCase() async throws {
        respond("""
        {"levels": [], "milestones": [], "quarter": "2026-Q4",
         "goals": [{"id": 1, "quarter": "2026-Q4", "ord": 1, "text_md": "Цель",
                    "milestone_code": null, "status": "open"}]}
        """)

        let board = try await client.putQuarterGoals(
            quarter: "2026-Q4",
            goals: [QuarterGoalInDTO(ord: 1, textMd: "Цель", milestoneCode: nil, status: "open")]
        )

        XCTAssertEqual(captured?.url?.path, "/api/v1/goals/quarter/2026-Q4")
        XCTAssertEqual(captured?.httpMethod, "PUT")
        XCTAssertEqual(captured?.value(forHTTPHeaderField: "Content-Type"), "application/json")
        XCTAssertEqual(captured?.value(forHTTPHeaderField: "X-API-Key"), "secret")
        let body = try XCTUnwrap(capturedBody)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: [[String: Any]]])
        let goal = try XCTUnwrap(json["goals"]?.first)
        XCTAssertEqual(goal["ord"] as? Int, 1)
        XCTAssertEqual(goal["text_md"] as? String, "Цель")
        XCTAssertEqual(goal["status"] as? String, "open")
        XCTAssertEqual(board.goals.first?.textMd, "Цель")
    }

    func testPutQuarterRefusalCarriesTheServersRussianReason() async {
        respond(#"{"detail": "Квартал 2026-Q4 не записан: место 1 занято дважды."}"#, status: 422)

        do {
            _ = try await client.putQuarterGoals(quarter: "2026-Q4", goals: [])
            XCTFail("expected 422")
        } catch {
            XCTAssertEqual(
                error as? GoalsWriteError,
                .rejected(status: 422, detail: "Квартал 2026-Q4 не записан: место 1 занято дважды.")
            )
        }
    }

    func testPutQuarterRefusalWithAnEnglishOrMissingReasonIsAPlainStatus() async {
        respond(#"{"detail": [{"msg": "field required"}]}"#, status: 422)

        do {
            _ = try await client.putQuarterGoals(quarter: "2026-Q4", goals: [])
            XCTFail("expected 422")
        } catch {
            XCTAssertEqual(error as? APIClientError, .unexpectedStatus(422))
        }
    }

    func testPutQuarterUnauthorizedStaysUnauthorized() async {
        respond(#"{"detail": "no"}"#, status: 401)

        do {
            _ = try await client.putQuarterGoals(quarter: "2026-Q4", goals: [])
            XCTFail("expected 401")
        } catch {
            XCTAssertEqual(error as? APIClientError, .unauthorized)
        }
    }
}
