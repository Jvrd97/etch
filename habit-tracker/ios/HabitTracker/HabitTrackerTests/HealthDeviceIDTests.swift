// [review:need-review] PHASE-03/132
// summary: the device id is minted once, survives reads, and fits the server's 64-character bound
import XCTest
@testable import HabitTracker

final class HealthDeviceIDTests: XCTestCase {
    private var defaults: UserDefaults!
    private let suite = "HealthDeviceIDTests"

    override func setUp() {
        super.setUp()
        defaults = UserDefaults(suiteName: suite)
        defaults.removePersistentDomain(forName: suite)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suite)
        super.tearDown()
    }

    func testIdIsMintedOnceAndStaysTheSame() {
        let first = HealthDeviceID.current(in: defaults)
        let second = HealthDeviceID.current(in: defaults)

        XCTAssertEqual(first, second)
        XCTAssertNotNil(UUID(uuidString: first))
        XCTAssertLessThanOrEqual(first.count, 64)
    }

    func testAFreshInstallGetsAnotherId() {
        let first = HealthDeviceID.current(in: defaults)
        defaults.removePersistentDomain(forName: suite)

        XCTAssertNotEqual(HealthDeviceID.current(in: defaults), first)
    }
}
