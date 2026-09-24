// [review:approved] PHASE-03/155
// summary: permits HTTPS destinations and HTTP only for exact loopback hosts; maps a refused response onto what to do with the batch
import XCTest
@testable import HabitAgent

final class AgentAPIClientTests: XCTestCase {
    func testHttpsServerIsAllowed() {
        XCTAssertEqual(
            AgentAPIClient.activityEndpoint(for: "https://habit.example"),
            URL(string: "https://habit.example/api/v1/agent/activity")
        )
    }

    func testHttpLocalhostIsAllowedForDevelopment() {
        XCTAssertEqual(
            AgentAPIClient.activityEndpoint(for: "http://localhost:8000"),
            URL(string: "http://localhost:8000/api/v1/agent/activity")
        )
        XCTAssertEqual(
            AgentAPIClient.activityEndpoint(for: "http://127.0.0.1:8000"),
            URL(string: "http://127.0.0.1:8000/api/v1/agent/activity")
        )
        XCTAssertEqual(
            AgentAPIClient.activityEndpoint(for: "http://[::1]:8000"),
            URL(string: "http://[::1]:8000/api/v1/agent/activity")
        )
    }

    func testHttpRemoteServerIsRejected() {
        XCTAssertNil(AgentAPIClient.activityEndpoint(for: "http://habit.example"))
        XCTAssertNil(AgentAPIClient.activityEndpoint(for: "http://192.168.1.20:8000"))
        XCTAssertNil(AgentAPIClient.activityEndpoint(for: "http://localhost.example"))
    }

    func testUnsupportedSchemesAndMissingHostsAreRejected() {
        XCTAssertNil(AgentAPIClient.activityEndpoint(for: "ftp://localhost/file"))
        XCTAssertNil(AgentAPIClient.activityEndpoint(for: "/api/v1"))
    }

    private func interval(_ bundleID: String) -> ActivityInterval {
        let moment = Date(timeIntervalSince1970: 1_800_000_000)
        return ActivityInterval(
            bundleID: bundleID, startedAt: moment, endedAt: moment.addingTimeInterval(5),
            localDate: "2027-01-15", utcOffsetMinutes: 0, switchCount: 0
        )
    }

    func testCatalogueRefusalNamesTheExactBundleThatWasSent() {
        let body = Data(#"{"detail":"Приложения com.apple.Safari нет в каталоге tracked_app. Заведите его."}"#.utf8)
        let sent = [interval("com.apple.SafariTechnologyPreview"), interval("com.apple.Safari")]
        XCTAssertEqual(AgentAPIClient.error(status: 422, body: body, sent: sent), .unknownApp(bundleID: "com.apple.Safari"))
    }

    func testValidationRefusalWithoutASentBundleIsAnInvalidBatch() {
        let body = Data(#"{"detail":[{"loc":["body","intervals"],"msg":"too long"}]}"#.utf8)
        XCTAssertEqual(AgentAPIClient.error(status: 422, body: body, sent: [interval("com.example.editor")]), .invalidBatch)
    }

    func testOtherStatusesStayRetryable() {
        XCTAssertEqual(AgentAPIClient.error(status: 401, body: Data(), sent: [interval("com.example.editor")]), .http(status: 401))
    }
}
