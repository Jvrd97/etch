// [review:need-review] PHASE-01/266
// summary: wire tests of the role endpoints — paths, methods and snake_case bodies of every call the screens make, the summary query, DELETE without a body, the confirm patch, and statuses mapped to APIClientError
import XCTest
@testable import HabitTracker

final class RolesAPIClientTests: XCTestCase {
    private var client: APIClient!
    private var captured: URLRequest?
    private var capturedBody: [String: Any]?

    override func setUp() {
        super.setUp()
        client = APIClient(
            baseURL: URL(string: "http://localhost:8879")!,
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
            self.capturedBody = Self.bodyData(of: request).flatMap {
                try? JSONSerialization.jsonObject(with: $0) as? [String: Any]
            }
            let response = HTTPURLResponse(
                url: request.url!, statusCode: status, httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(body.utf8))
        }
    }

    /// URLProtocol sees the body as a stream, not as `httpBody`.
    private static func bodyData(of request: URLRequest) -> Data? {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return nil }
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

    func testDayAndDirectoryDecodeAndAskTheBarePaths() async throws {
        respond(RolesFixtures.dayJSON)
        let day = try await client.fetchRoleDay()
        XCTAssertEqual(captured?.url?.path, "/api/v1/roles/day")
        XCTAssertEqual(day.blocks[1].appName, "Xcode")
        XCTAssertNil(day.roles[1].targetSharePct)

        respond(RolesFixtures.rolesJSON)
        let roles = try await client.fetchRoles()
        XCTAssertEqual(captured?.url?.path, "/api/v1/roles")
        XCTAssertEqual(roles.map(\.code), ["cto", "dev"])
    }

    func testSummaryCarriesTheBoundsInTheQuery() async throws {
        respond(RolesFixtures.summaryJSON)
        let summary = try await client.fetchRoleSummary(dateFrom: "2026-08-21", dateTo: "2026-08-27")
        let items = URLComponents(url: try XCTUnwrap(captured?.url), resolvingAgainstBaseURL: false)?.queryItems
        XCTAssertEqual(captured?.url?.path, "/api/v1/roles/summary")
        XCTAssertEqual(items?.first { $0.name == "date_from" }?.value, "2026-08-21")
        XCTAssertEqual(items?.first { $0.name == "date_to" }?.value, "2026-08-27")
        XCTAssertTrue(summary.rulesLag)
        XCTAssertEqual(summary.roles[0].actCounts["adr_written"], 2)
    }

    func testRuleDryRunPostsTheDraftInSnakeCase() async throws {
        respond(RolesFixtures.dryRunJSON)
        let draft = RoleRuleDraftDTO(
            roleCode: "dev", source: "git", matcherKind: "commit_prefix", pattern: "feat(", priority: 100
        )
        let run = try await client.dryRunRoleRule(draft)
        XCTAssertEqual(captured?.httpMethod, "POST")
        XCTAssertEqual(captured?.url?.path, "/api/v1/role-rules/dry-run")
        XCTAssertEqual(capturedBody?["role_code"] as? String, "dev")
        XCTAssertEqual(capturedBody?["matcher_kind"] as? String, "commit_prefix")
        XCTAssertEqual(capturedBody?["priority"] as? Int, 100)
        XCTAssertEqual(run.takenFrom["5"], 3)
    }

    func testRuleSwitchPatchesOnlyIsActive() async throws {
        respond(RolesFixtures.ruleJSON)
        _ = try await client.setRoleRuleActive(id: 5, isActive: false)
        XCTAssertEqual(captured?.httpMethod, "PATCH")
        XCTAssertEqual(captured?.url?.path, "/api/v1/role-rules/5")
        XCTAssertEqual(capturedBody?.keys.sorted(), ["is_active"])
        XCTAssertEqual(capturedBody?["is_active"] as? Bool, false)
    }

    func testReclassifyPostsTheRange() async throws {
        respond(RolesFixtures.reclassifiedJSON)
        let result = try await client.reclassifyRoles(dateFrom: "2026-07-29", dateTo: "2026-08-27")
        XCTAssertEqual(captured?.url?.path, "/api/v1/roles/reclassify")
        XCTAssertEqual(capturedBody?["date_from"] as? String, "2026-07-29")
        XCTAssertEqual(result.protected, 2)
    }

    func testBlockWritesUseTheirOwnPathsAndBodies() async throws {
        respond(RolesFixtures.blockJSON)
        _ = try await client.addRoleTimeBlock(
            RoleTimeBlockDraftDTO(roleCode: "cto", minutes: 90, workDay: "2026-08-27", note: nil)
        )
        XCTAssertEqual(captured?.url?.path, "/api/v1/role-time-blocks")
        XCTAssertEqual(capturedBody?["minutes"] as? Int, 90)
        XCTAssertEqual(capturedBody?["work_day"] as? String, "2026-08-27")

        _ = try await client.confirmRoleTimeBlock(id: 12)
        XCTAssertEqual(captured?.httpMethod, "PATCH")
        XCTAssertEqual(captured?.url?.path, "/api/v1/role-time-blocks/12")
        XCTAssertEqual(capturedBody?["confidence"] as? String, "confirmed")

        respond("")
        try await client.deleteRoleTimeBlock(id: 12)
        XCTAssertEqual(captured?.httpMethod, "DELETE")
        XCTAssertEqual(captured?.url?.path, "/api/v1/role-time-blocks/12")
    }

    func testServerRefusalIsAStatusError() async {
        respond("{}", status: 422)
        do {
            _ = try await client.addRoleAct(
                RoleActDraftDTO(roleCode: "cto", actKind: "adr_written", title: "x", workDay: "2026-08-27")
            )
            XCTFail("expected a failure")
        } catch {
            XCTAssertEqual(error as? APIClientError, .unexpectedStatus(422))
        }
    }
}
