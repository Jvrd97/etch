// [review:need-review] PHASE-01/208
// summary: tests for the single production factory APIClient.live() and for helpers reachable from a feature extension
import XCTest
@testable import HabitTracker

/// A feature's own `APIClient+<Feature>.swift` builds its endpoints on the shared
/// helpers; this probe stands in for one, so the test fails to compile if they go private.
private extension APIClient {
    func fetchProbe() async throws -> [CategoryDTO] {
        try await getJSON(path: "/probe", query: [URLQueryItem(name: "q", value: "1")])
    }
}

final class APIClientLiveTests: XCTestCase {
    private static let defaultsSuite = "com.habittracker.tests.live"
    private let keychain = KeychainStore(service: "com.habittracker.tests.live")
    private var defaults: UserDefaults!

    override func setUpWithError() throws {
        try super.setUpWithError()
        defaults = UserDefaults(suiteName: Self.defaultsSuite)
        defaults.removePersistentDomain(forName: Self.defaultsSuite)
    }

    override func tearDownWithError() throws {
        defaults.removePersistentDomain(forName: Self.defaultsSuite)
        try keychain.delete(SettingsViewModel.apiKeyKeychainKey)
        MockURLProtocol.requestHandler = nil
        try super.tearDownWithError()
    }

    private func makeLive(timeout: TimeInterval = APIClient.defaultTimeout) -> APIClient? {
        APIClient.live(
            timeout: timeout,
            defaults: defaults,
            keychain: keychain,
            session: MockURLProtocol.makeSession()
        )
    }

    /// Answers every request with an empty JSON list and records what was sent.
    private func captureRequests() -> () -> [URLRequest] {
        var captured: [URLRequest] = []
        MockURLProtocol.requestHandler = { request in
            captured.append(request)
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 200, httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data("[]".utf8))
        }
        return { captured }
    }

    func testLiveIsNilWithoutStoredServerAddress() {
        XCTAssertNil(makeLive())
    }

    func testLiveIsNilForUnparseableServerAddress() {
        defaults.set("not a url", forKey: SettingsViewModel.serverAddressDefaultsKey)

        XCTAssertNil(makeLive())
    }

    func testLiveTargetsStoredAddressAndSendsKeychainKey() async throws {
        defaults.set("http://100.64.0.1:8000", forKey: SettingsViewModel.serverAddressDefaultsKey)
        try keychain.save("stored-key", for: SettingsViewModel.apiKeyKeychainKey)
        let requests = captureRequests()

        _ = try await XCTUnwrap(makeLive()).fetchCategories()

        let request = try XCTUnwrap(requests().first)
        XCTAssertEqual(request.url?.absoluteString, "http://100.64.0.1:8000/api/v1/categories")
        XCTAssertEqual(request.value(forHTTPHeaderField: APIClient.apiKeyHeader), "stored-key")
    }

    func testLiveReadsKeyOnEveryRequestSoSettingsChangesApplyWithoutRebuild() async throws {
        defaults.set("http://100.64.0.1:8000", forKey: SettingsViewModel.serverAddressDefaultsKey)
        let requests = captureRequests()
        let client = try XCTUnwrap(makeLive())

        _ = try await client.fetchCategories()
        try keychain.save("new-key", for: SettingsViewModel.apiKeyKeychainKey)
        _ = try await client.fetchCategories()

        XCTAssertEqual(
            requests().map { $0.value(forHTTPHeaderField: APIClient.apiKeyHeader) },
            [nil, "new-key"]
        )
    }

    func testLiveAppliesRequestedTimeout() async throws {
        defaults.set("http://100.64.0.1:8000", forKey: SettingsViewModel.serverAddressDefaultsKey)
        let requests = captureRequests()
        let slowEndpointTimeout: TimeInterval = 120

        _ = try await XCTUnwrap(makeLive(timeout: slowEndpointTimeout)).fetchCategories()

        XCTAssertEqual(try XCTUnwrap(requests().first).timeoutInterval, slowEndpointTimeout)
    }

    func testFeatureExtensionReachesSharedHelpers() async throws {
        defaults.set("http://100.64.0.1:8000/base", forKey: SettingsViewModel.serverAddressDefaultsKey)
        let requests = captureRequests()

        _ = try await XCTUnwrap(makeLive()).fetchProbe()

        XCTAssertEqual(
            try XCTUnwrap(requests().first).url?.absoluteString,
            "http://100.64.0.1:8000/base/api/v1/probe?q=1"
        )
    }
}
