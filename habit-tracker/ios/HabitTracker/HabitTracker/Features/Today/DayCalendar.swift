// [review:need-review] PHASE-03/294
// summary: the month grid of the day picker for the relapse date — pure over `yyyy-MM-dd` strings (Monday first, no locale and no time zone), and the SwiftUI month view on top of it with the days after the maximum day switched off
import SwiftUI

enum DayCalendar {
    private static let monthNames = [
        "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    ]
    private static let daysPerWeek = 7

    /// One month: its title and the cells of its weeks, a nil cell being a blank before the 1st or after the last day.
    struct Month: Equatable {
        let title: String
        let firstDay: String
        let cells: [String?]
    }

    static func month(containing day: String) -> Month {
        let parts = day.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3, (1...12).contains(parts[1]) else {
            return Month(title: day, firstDay: day, cells: [])
        }
        let first = String(format: "%04d-%02d-01", parts[0], parts[1])
        let firstNumber = RelapseAnalysis.dayNumber(of: first)
        let nextFirst = firstDay(ofMonthAfter: first)
        let length = RelapseAnalysis.dayNumber(of: nextFirst) - firstNumber
        let leading = RelapseAnalysis.weekdayLabels.firstIndex(of: RelapseAnalysis.formatWeekday(first)) ?? 0
        var cells: [String?] = Array(repeating: nil, count: leading)
        cells += (0..<length).map { RelapseAnalysis.isoDate(of: firstNumber + $0) }
        while cells.count % daysPerWeek != 0 { cells.append(nil) }
        return Month(title: "\(monthNames[parts[1] - 1]) \(parts[0])", firstDay: first, cells: cells)
    }

    /// The 1st of the month `offset` months from the one that holds `day`.
    static func firstDay(ofMonthAfter day: String, by offset: Int = 1) -> String {
        let parts = day.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return day }
        let index = parts[0] * 12 + (parts[1] - 1) + offset
        return String(format: "%04d-%02d-01", index / 12, index % 12 + 1)
    }

    /// The day `offset` days from `day`.
    static func day(_ day: String, plusDays offset: Int) -> String {
        RelapseAnalysis.isoDate(of: RelapseAnalysis.dayNumber(of: day) + offset)
    }
}

/// A month at a time, tap a day to choose it. Days after `maxDay` are off: a relapse is not recorded ahead.
struct DayCalendarPicker: View {
    @Binding var selection: String
    let maxDay: String
    @State private var shownMonth: String

    init(selection: Binding<String>, maxDay: String) {
        _selection = selection
        self.maxDay = maxDay
        _shownMonth = State(initialValue: DayCalendar.month(containing: selection.wrappedValue).firstDay)
    }

    private static let columns = Array(repeating: GridItem(.flexible(), spacing: 0), count: 7)

    var body: some View {
        let month = DayCalendar.month(containing: shownMonth)
        VStack(spacing: DS.Spacing.sm) {
            HStack {
                Button { shownMonth = DayCalendar.firstDay(ofMonthAfter: shownMonth, by: -1) } label: {
                    Image(systemName: "chevron.left").frame(width: 44, height: 44)
                }
                .accessibilityLabel("Предыдущий месяц")
                Spacer()
                Text(month.title)
                    .font(DS.Typography.card)
                    .foregroundStyle(DS.Palette.textPrimary)
                Spacer()
                Button { shownMonth = DayCalendar.firstDay(ofMonthAfter: shownMonth) } label: {
                    Image(systemName: "chevron.right").frame(width: 44, height: 44)
                }
                .disabled(DayCalendar.firstDay(ofMonthAfter: shownMonth) > maxDay)
                .accessibilityLabel("Следующий месяц")
            }
            .foregroundStyle(DS.Palette.lime)
            LazyVGrid(columns: Self.columns, spacing: 0) {
                ForEach(RelapseAnalysis.weekdayLabels, id: \.self) { label in
                    Text(label)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                        .frame(height: 28)
                }
                ForEach(Array(month.cells.enumerated()), id: \.offset) { _, cell in
                    if let cell {
                        dayButton(cell)
                    } else {
                        Color.clear.frame(height: 44)
                    }
                }
            }
        }
    }

    private func dayButton(_ day: String) -> some View {
        let isSelected = day == selection
        let number = day.split(separator: "-").last.flatMap { Int($0) } ?? 0
        return Button {
            selection = day
        } label: {
            Text("\(number)")
                .font(DS.Typography.body)
                .monospacedDigit()
                .foregroundStyle(isSelected ? Color.black : DS.Palette.textPrimary)
                .frame(maxWidth: .infinity, minHeight: 44)
                .background(Circle().fill(isSelected ? DS.Palette.lime : Color.clear).padding(2))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(day > maxDay)
        .opacity(day > maxDay ? 0.3 : 1)
        .accessibilityLabel(RelapseAnalysis.formatDay(day))
        .accessibilityIdentifier("daycalendar.\(day)")
    }
}
