// [review:need-review] PHASE-01/266
// summary: tests of the role texts — minutes and Russian plurals (the teens), the unassigned line, the markup source of an automatic block, the target always called a hypothesis, the lag note, period bounds on server days, dry-run and re-markup lines
import XCTest
@testable import HabitTracker

final class RolesFormatTests: XCTestCase {
    func testMinutesReadAsHoursAndMinutes() {
        XCTAssertEqual(RolesFormat.minutes(0), "0 мин")
        XCTAssertEqual(RolesFormat.minutes(45), "45 мин")
        XCTAssertEqual(RolesFormat.minutes(120), "2 ч")
        XCTAssertEqual(RolesFormat.minutes(90), "1 ч 30 мин")
        XCTAssertEqual(RolesFormat.summaryMinutes(120), "2 ч 0 мин")
    }

    func testActsPluralTeensTakeTheManyForm() {
        XCTAssertEqual(RolesFormat.actsCount(1), "1 акт")
        XCTAssertEqual(RolesFormat.actsCount(2), "2 акта")
        XCTAssertEqual(RolesFormat.actsCount(5), "5 актов")
        XCTAssertEqual(RolesFormat.actsCount(11), "11 актов")
        XCTAssertEqual(RolesFormat.actsCount(21), "21 акт")
    }

    func testDayLines() throws {
        let day = try RolesFixtures.day()
        XCTAssertEqual(RolesFormat.actsSummary(day), "Тимлид — 2 акта")
        XCTAssertEqual(RolesFormat.unassignedLine(day), "не отнесено: 20%")
        XCTAssertEqual(RolesFormat.targetShareLine(day.roles[0]), "цель 40% — гипотеза, не норма")
        XCTAssertNil(RolesFormat.targetShareLine(day.roles[1]))
        XCTAssertEqual(RolesFormat.actLine(day.acts[0]), "написан ADR: ADR-0020")
        XCTAssertNil(RolesFormat.fromPlanLine(day.acts[0]))
        XCTAssertEqual(RolesFormat.fromPlanLine(day.acts[1]), "из плана: Созвон с кандидатом")
    }

    func testMarkupSourceOnlyForAutomaticBlocks() throws {
        let blocks = try RolesFixtures.day().blocks
        XCTAssertNil(RolesFormat.markupSource(blocks[0]))
        XCTAssertEqual(
            RolesFormat.markupSource(blocks[1]),
            "автоматически: Xcode · bundle_id = com.apple.dt.Xcode"
        )
        XCTAssertEqual(RolesFormat.blockLine(blocks[0]), "1 ч 30 мин · cto · найм · вручную")
        XCTAssertFalse(RolesFormat.canConfirm(blocks[0]))
        XCTAssertTrue(RolesFormat.canConfirm(blocks[1]))
    }

    func testEmptyDayHasNoUnassignedLine() throws {
        var json = RolesFixtures.dayJSON
        json = json.replacingOccurrences(of: "\"minutes\":30,\"share_pct\":20,\"target_share_pct\":null,\"act_count\":0}]", with: "\"minutes\":0,\"share_pct\":0,\"target_share_pct\":null,\"act_count\":0}]")
        let day: RoleDayDTO = try RolesFixtures.decode(json)
        XCTAssertNil(RolesFormat.unassignedLine(day))
    }

    func testSummaryRowsAndLagNote() throws {
        let summary = try RolesFixtures.summary()
        let rows = RolesFormat.workingRoles(summary)
        XCTAssertEqual(rows.count, 1)
        XCTAssertEqual(RolesFormat.summaryRowLine(rows[0]), "5 ч 0 мин · 50% · цель 40% · +10 п.п.")
        XCTAssertEqual(RolesFormat.actsText(rows[0]), "adr_written × 2, hiring_step × 1")
        XCTAssertTrue(RolesFormat.unassignedNote(summary).hasPrefix("правила разметки отстали"))
    }

    func testRangeCountsInclusiveServerDays() {
        let week = RolesFormat.range(endingOn: "2026-08-27", period: .week)
        XCTAssertEqual(week?.from, "2026-08-21")
        XCTAssertEqual(week?.to, "2026-08-27")
        XCTAssertEqual(RolesFormat.range(endingOn: "2026-03-01", period: .month)?.from, "2026-01-31")
        XCTAssertNil(RolesFormat.range(endingOn: "not a day", period: .week))
    }

    func testDryRunAndReclassifyLines() throws {
        let run = try RolesFixtures.dryRun()
        let rules = try RolesFixtures.rules()
        XCTAssertEqual(
            RolesFormat.dryRunSummary(run),
            "Зацепило интервалов: 7, актов: 1 из 40 строк за 2026-07-29 — 2026-08-27."
        )
        XCTAssertEqual(
            RolesFormat.takenFromLines(run, rules: rules),
            ["Отбирает у «com.apple.dt.Xcode»: 3", "Ничьих совпадений: 4"]
        )
        let result = try RolesFixtures.reclassified()
        XCTAssertTrue(RolesFormat.protectedLine(result).hasSuffix("не тронуто: 2."))
        XCTAssertEqual(RolesFormat.reclassifyLines(result, roles: try RolesFixtures.roles()), ["Тимлид: 40% → 55%"])
    }
}
