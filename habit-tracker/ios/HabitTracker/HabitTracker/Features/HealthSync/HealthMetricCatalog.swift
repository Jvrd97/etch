// [review:need-review] PHASE-02/65, PHASE-03/234, PHASE-03/233, PHASE-03/238, PHASE-03/272
// summary: every HealthKit quantity type on iPhone and Watch except cycle tracking — kind from HealthKit's own aggregation style, the HealthKit unit it is read in, the unit the server is sent, names and screen groups — and every category type but cycle tracking: sleep folded into nights by the server, the rest into minutes or counts per hour and clipped to the reading window

import HealthKit

enum HealthMetricGroup: String, CaseIterable, Hashable, Sendable {
    case movement
    case mobility
    case heart
    case body
    case nutrition
    case hearing
    case other

    var title: String {
        switch self {
        case .movement: "Движение и энергия"
        case .mobility: "Подвижность"
        case .heart: "Сердце и дыхание"
        case .body: "Тело"
        case .nutrition: "Питание"
        case .hearing: "Слух"
        case .other: "Другое"
        }
    }
}

/// Mirrors `MetricKind` in the server catalogue and HealthKit's own aggregation style.
enum HealthMetricKind: Equatable, Sendable {
    /// An amount over an interval (steps): read as HealthKit's hourly sums.
    case cumulative
    /// A reading at a moment (resting heart rate): read as samples.
    case discrete
}

struct HealthMetricDefinition: Identifiable, Equatable, Sendable {
    let typeIdentifier: HKQuantityTypeIdentifier
    let displayName: String
    let group: HealthMetricGroup
    let kind: HealthMetricKind
    /// HealthKit unit string the value is read in.
    let unit: String
    /// Unit string the server is told the value is in. Differs from `unit` only for
    /// percentages: `HKUnit.percent()` yields 0.97, which the server calls `fraction`.
    let wireUnit: String

    var identifier: String { typeIdentifier.rawValue }
    var id: String { identifier }
}

/// Every quantity type HealthKit reads on iPhone and Watch, except basal body temperature,
/// which belongs to Cycle Tracking (owner's decision, #272). The server catalogue
/// (`app/health/catalog.py`) holds the same identifiers, kinds and units;
/// `HealthMetricCatalogTests` holds both to `metric_catalog.json`.
enum HealthMetricCatalog {
    static let metrics: [HealthMetricDefinition] = baseline + newerTypes

    /// Types that exist on iOS 17, the deployment target.
    private static let baseline: [HealthMetricDefinition] = [
        metric(.stepCount, "Шаги", .movement, "count"),
        metric(.distanceWalkingRunning, "Дистанция ходьбы и бега", .movement, "m"),
        metric(.flightsClimbed, "Этажи", .movement, "count"),
        metric(.activeEnergyBurned, "Активная энергия", .movement, "kcal"),
        metric(.basalEnergyBurned, "Базальная энергия", .movement, "kcal"),
        metric(.appleExerciseTime, "Минуты тренировки", .movement, "min"),
        metric(.appleStandTime, "Время стоя", .movement, "min"),
        metric(.heartRate, "Пульс", .heart, "count/min"),
        metric(.restingHeartRate, "Пульс покоя", .heart, "count/min"),
        metric(.walkingHeartRateAverage, "Средний пульс при ходьбе", .heart, "count/min"),
        metric(.heartRateVariabilitySDNN, "Вариабельность пульса (SDNN)", .heart, "ms"),
        metric(.respiratoryRate, "Частота дыхания", .heart, "count/min"),
        metric(.oxygenSaturation, "Сатурация", .heart, "%"),
        metric(.vo2Max, "VO2max", .heart, "mL/(kg*min)"),
        metric(.bodyMass, "Вес", .body, "kg"),
        metric(.bodyFatPercentage, "Процент жира", .body, "%"),
        metric(.leanBodyMass, "Мышечная масса", .body, "kg"),
        metric(.bodyMassIndex, "Индекс массы тела", .body, "count"),
        metric(.height, "Рост", .body, "cm"),
        metric(.dietaryEnergyConsumed, "Съеденные калории", .nutrition, "kcal"),
        metric(.dietaryProtein, "Белки", .nutrition, "g"),
        metric(.dietaryFatTotal, "Жиры", .nutrition, "g"),
        metric(.dietaryCarbohydrates, "Углеводы", .nutrition, "g"),
        metric(.dietaryWater, "Вода", .nutrition, "mL"),
        metric(.appleMoveTime, "Минуты движения", .movement, "min"),
        metric(.timeInDaylight, "Время на дневном свете", .movement, "min"),
        metric(.distanceCycling, "Дистанция на велосипеде", .movement, "m"),
        metric(.distanceWheelchair, "Дистанция на кресле-коляске", .movement, "m"),
        metric(.pushCount, "Толчки кресла-коляски", .movement, "count"),
        metric(.distanceSwimming, "Дистанция в плавании", .movement, "m"),
        metric(.swimmingStrokeCount, "Гребки в плавании", .movement, "count"),
        metric(.distanceDownhillSnowSports, "Дистанция на горных лыжах и сноуборде", .movement, "m"),
        metric(.nikeFuel, "NikeFuel", .movement, "count"),
        metric(.physicalEffort, "Физическая нагрузка", .movement, "kcal/(kg*hr)"),
        metric(.runningSpeed, "Скорость бега", .movement, "m/s"),
        metric(.runningPower, "Мощность бега", .movement, "W"),
        metric(.runningStrideLength, "Длина шага при беге", .movement, "m"),
        metric(.runningVerticalOscillation, "Вертикальные колебания при беге", .movement, "cm"),
        metric(.runningGroundContactTime, "Время контакта с землёй при беге", .movement, "ms"),
        metric(.cyclingSpeed, "Скорость на велосипеде", .movement, "m/s"),
        metric(.cyclingPower, "Мощность на велосипеде", .movement, "W"),
        metric(.cyclingFunctionalThresholdPower, "Функциональная пороговая мощность", .movement, "W"),
        metric(.cyclingCadence, "Каденс на велосипеде", .movement, "count/min"),
        metric(.underwaterDepth, "Глубина под водой", .movement, "m"),
        metric(.waterTemperature, "Температура воды", .movement, "degC"),
        metric(.walkingSpeed, "Скорость ходьбы", .mobility, "m/s"),
        metric(.walkingStepLength, "Длина шага", .mobility, "cm"),
        metric(.walkingAsymmetryPercentage, "Асимметрия ходьбы", .mobility, "%"),
        metric(.walkingDoubleSupportPercentage, "Время двойной опоры", .mobility, "%"),
        metric(.appleWalkingSteadiness, "Устойчивость при ходьбе", .mobility, "%"),
        metric(.sixMinuteWalkTestDistance, "Дистанция шестиминутной ходьбы", .mobility, "m"),
        metric(.stairAscentSpeed, "Скорость подъёма по лестнице", .mobility, "m/s"),
        metric(.stairDescentSpeed, "Скорость спуска по лестнице", .mobility, "m/s"),
        metric(.heartRateRecoveryOneMinute, "Восстановление пульса за минуту", .heart, "count/min"),
        metric(.atrialFibrillationBurden, "Доля фибрилляции предсердий", .heart, "%"),
        metric(.peripheralPerfusionIndex, "Индекс периферической перфузии", .heart, "%"),
        metric(.bloodPressureSystolic, "Систолическое давление", .heart, "mmHg"),
        metric(.bloodPressureDiastolic, "Диастолическое давление", .heart, "mmHg"),
        metric(.forcedVitalCapacity, "Форсированная жизненная ёмкость лёгких", .heart, "L"),
        metric(.forcedExpiratoryVolume1, "Объём форсированного выдоха за секунду", .heart, "L"),
        metric(.peakExpiratoryFlowRate, "Пиковая скорость выдоха", .heart, "L/min"),
        metric(.inhalerUsage, "Использование ингалятора", .heart, "count"),
        metric(.waistCircumference, "Обхват талии", .body, "cm"),
        metric(.bodyTemperature, "Температура тела", .body, "degC"),
        metric(.appleSleepingWristTemperature, "Температура запястья во сне", .body, "degC"),
        metric(.electrodermalActivity, "Электродермальная активность", .body, "mcS"),
        metric(.environmentalAudioExposure, "Шум окружения", .hearing, "dBASPL"),
        metric(.headphoneAudioExposure, "Громкость в наушниках", .hearing, "dBASPL"),
        metric(.environmentalSoundReduction, "Шумоподавление", .hearing, "dBASPL"),
        metric(.dietaryFiber, "Клетчатка", .nutrition, "g"),
        metric(.dietarySugar, "Сахар", .nutrition, "g"),
        metric(.dietaryFatSaturated, "Насыщенные жиры", .nutrition, "g"),
        metric(.dietaryFatMonounsaturated, "Мононенасыщенные жиры", .nutrition, "g"),
        metric(.dietaryFatPolyunsaturated, "Полиненасыщенные жиры", .nutrition, "g"),
        metric(.dietaryCholesterol, "Холестерин", .nutrition, "mg"),
        metric(.dietarySodium, "Натрий", .nutrition, "mg"),
        metric(.dietaryPotassium, "Калий", .nutrition, "mg"),
        metric(.dietaryCalcium, "Кальций", .nutrition, "mg"),
        metric(.dietaryIron, "Железо", .nutrition, "mg"),
        metric(.dietaryMagnesium, "Магний", .nutrition, "mg"),
        metric(.dietaryPhosphorus, "Фосфор", .nutrition, "mg"),
        metric(.dietaryZinc, "Цинк", .nutrition, "mg"),
        metric(.dietaryCopper, "Медь", .nutrition, "mg"),
        metric(.dietaryManganese, "Марганец", .nutrition, "mg"),
        metric(.dietaryChloride, "Хлорид", .nutrition, "mg"),
        metric(.dietaryCaffeine, "Кофеин", .nutrition, "mg"),
        metric(.dietaryVitaminC, "Витамин C", .nutrition, "mg"),
        metric(.dietaryVitaminE, "Витамин E", .nutrition, "mg"),
        metric(.dietaryVitaminB6, "Витамин B6", .nutrition, "mg"),
        metric(.dietaryThiamin, "Тиамин (B1)", .nutrition, "mg"),
        metric(.dietaryRiboflavin, "Рибофлавин (B2)", .nutrition, "mg"),
        metric(.dietaryNiacin, "Ниацин (B3)", .nutrition, "mg"),
        metric(.dietaryPantothenicAcid, "Пантотеновая кислота (B5)", .nutrition, "mg"),
        metric(.dietaryVitaminA, "Витамин A", .nutrition, "mcg"),
        metric(.dietaryVitaminB12, "Витамин B12", .nutrition, "mcg"),
        metric(.dietaryVitaminD, "Витамин D", .nutrition, "mcg"),
        metric(.dietaryVitaminK, "Витамин K", .nutrition, "mcg"),
        metric(.dietaryFolate, "Фолат", .nutrition, "mcg"),
        metric(.dietaryBiotin, "Биотин", .nutrition, "mcg"),
        metric(.dietaryIodine, "Йод", .nutrition, "mcg"),
        metric(.dietarySelenium, "Селен", .nutrition, "mcg"),
        metric(.dietaryChromium, "Хром", .nutrition, "mcg"),
        metric(.dietaryMolybdenum, "Молибден", .nutrition, "mcg"),
        metric(.numberOfAlcoholicBeverages, "Алкогольные напитки", .nutrition, "count"),
        metric(.bloodGlucose, "Глюкоза крови", .other, "mg/dL"),
        metric(.insulinDelivery, "Инсулин", .other, "IU"),
        metric(.bloodAlcoholContent, "Алкоголь в крови", .other, "%"),
        metric(.numberOfTimesFallen, "Падения", .other, "count"),
        metric(.uvExposure, "УФ-индекс", .other, "count"),
    ]

    private static var newerTypes: [HealthMetricDefinition] {
        guard #available(iOS 18.0, *) else {
            return []
        }
        return [
            metric(.distanceCrossCountrySkiing, "Дистанция на беговых лыжах", .movement, "m"),
            metric(.distancePaddleSports, "Дистанция на каяке и SUP", .movement, "m"),
            metric(.distanceRowing, "Дистанция гребли", .movement, "m"),
            metric(.distanceSkatingSports, "Дистанция на коньках", .movement, "m"),
            metric(.workoutEffortScore, "Оценка нагрузки тренировки", .movement, "appleEffortScore"),
            metric(.estimatedWorkoutEffortScore, "Расчётная нагрузка тренировки", .movement, "appleEffortScore"),
            metric(.crossCountrySkiingSpeed, "Скорость на беговых лыжах", .movement, "m/s"),
            metric(.paddleSportsSpeed, "Скорость на каяке и SUP", .movement, "m/s"),
            metric(.rowingSpeed, "Скорость гребли", .movement, "m/s"),
            metric(.appleSleepingBreathingDisturbances, "Нарушения дыхания во сне", .heart, "count"),
        ]
    }

    private static func metric(
        _ identifier: HKQuantityTypeIdentifier,
        _ displayName: String,
        _ group: HealthMetricGroup,
        _ unit: String
    ) -> HealthMetricDefinition {
        HealthMetricDefinition(
            typeIdentifier: identifier,
            displayName: displayName,
            group: group,
            // HKStatisticsCollectionQuery refuses `.cumulativeSum` on any other style.
            kind: HKQuantityType(identifier).aggregationStyle == .cumulative ? .cumulative : .discrete,
            unit: unit,
            wireUnit: unit == "%" ? "fraction" : unit
        )
    }
}

/// A HealthKit category type the pump sends as raw intervals (`category_samples`):
/// HealthKit's raw category value, a start and an end. The server decides what the
/// value means by its catalogue kind; the app does not fold anything.
struct HealthCategoryDefinition: Identifiable, Equatable, Sendable {
    let typeIdentifier: HKCategoryTypeIdentifier
    let displayName: String
    /// The server catalogue kind: `sleep` folds into nights by wake date, `cumulative`
    /// into hourly minutes or counts.
    let serverKind: String
    /// The server catalogue's canonical unit: what one interval is worth there.
    let serverUnit: String
    /// How long before the window's first midnight to start reading. The server sends
    /// every interval of a night to one row and overwrites it, so the first night of
    /// the window has to arrive whole.
    let lead: TimeInterval

    var identifier: String { typeIdentifier.rawValue }
    var id: String { identifier }

    /// An hourly type is cut at the start of the reading window. The server overwrites
    /// every hour a chunk touches, and a session that began before the window would
    /// otherwise overwrite the hour before it with only its own part. A night is never
    /// cut: the server folds it whole by its end.
    var clipsToWindow: Bool { serverKind == HealthCategoryCatalog.hourlyKind }
}

/// Every category type HealthKit reads on iPhone and Watch, except the Cycle Tracking
/// section, which the app does not even ask to read (#272).
enum HealthCategoryCatalog {
    /// Server `NIGHT_BOUNDARY_HOUR` (`app/health/sleep.py`): the night that ends on a date
    /// collects every interval ending after 18:00 the evening before, six hours before midnight.
    static let nightLead: TimeInterval = 6 * 60 * 60
    /// The server kind of every category type but sleep (`app/health/categories.py`).
    static let hourlyKind = "cumulative"

    static let sleep = HealthCategoryDefinition(
        typeIdentifier: .sleepAnalysis, displayName: "Сон", serverKind: "sleep", serverUnit: "min", lead: nightLead
    )

    static let categories: [HealthCategoryDefinition] = [sleep] + baseline + newerTypes

    private static let baseline: [HealthCategoryDefinition] = [
        hours(.appleStandHour, "Часы с разминкой", "count"),
        hours(.mindfulSession, "Осознанность", "min"),
        hours(.highHeartRateEvent, "Уведомления о высоком пульсе", "count"),
        hours(.lowHeartRateEvent, "Уведомления о низком пульсе", "count"),
        hours(.irregularHeartRhythmEvent, "Уведомления о нерегулярном ритме", "count"),
        hours(.lowCardioFitnessEvent, "Уведомления о низкой кардиоподготовке", "count"),
        hours(.appleWalkingSteadinessEvent, "Уведомления об устойчивости при ходьбе", "count"),
        hours(.environmentalAudioExposureEvent, "Уведомления о громком окружении", "count"),
        hours(.headphoneAudioExposureEvent, "Уведомления о громкости наушников", "count"),
        hours(.toothbrushingEvent, "Чистка зубов", "count"),
        hours(.handwashingEvent, "Мытьё рук", "count"),
        hours(.abdominalCramps, "Спазмы в животе", "count"),
        hours(.acne, "Акне", "count"),
        hours(.appetiteChanges, "Изменения аппетита", "count"),
        hours(.bladderIncontinence, "Недержание мочи", "count"),
        hours(.bloating, "Вздутие", "count"),
        hours(.breastPain, "Боль в молочных железах", "count"),
        hours(.chestTightnessOrPain, "Стеснение или боль в груди", "count"),
        hours(.chills, "Озноб", "count"),
        hours(.constipation, "Запор", "count"),
        hours(.coughing, "Кашель", "count"),
        hours(.diarrhea, "Диарея", "count"),
        hours(.dizziness, "Головокружение", "count"),
        hours(.drySkin, "Сухость кожи", "count"),
        hours(.fainting, "Обморок", "count"),
        hours(.fatigue, "Усталость", "count"),
        hours(.fever, "Жар", "count"),
        hours(.generalizedBodyAche, "Ломота в теле", "count"),
        hours(.hairLoss, "Выпадение волос", "count"),
        hours(.headache, "Головная боль", "count"),
        hours(.heartburn, "Изжога", "count"),
        hours(.hotFlashes, "Приливы", "count"),
        hours(.lossOfSmell, "Потеря обоняния", "count"),
        hours(.lossOfTaste, "Потеря вкуса", "count"),
        hours(.lowerBackPain, "Боль в пояснице", "count"),
        hours(.memoryLapse, "Провалы в памяти", "count"),
        hours(.moodChanges, "Перепады настроения", "count"),
        hours(.nausea, "Тошнота", "count"),
        hours(.nightSweats, "Ночная потливость", "count"),
        hours(.pelvicPain, "Тазовая боль", "count"),
        hours(.rapidPoundingOrFlutteringHeartbeat, "Учащённое сердцебиение", "count"),
        hours(.runnyNose, "Насморк", "count"),
        hours(.shortnessOfBreath, "Одышка", "count"),
        hours(.sinusCongestion, "Заложенность носа", "count"),
        hours(.skippedHeartbeat, "Перебои сердцебиения", "count"),
        hours(.sleepChanges, "Изменения сна", "count"),
        hours(.soreThroat, "Боль в горле", "count"),
        hours(.vaginalDryness, "Сухость влагалища", "count"),
        hours(.vomiting, "Рвота", "count"),
        hours(.wheezing, "Хрипы", "count"),
    ]

    private static var newerTypes: [HealthCategoryDefinition] {
        var types: [HealthCategoryDefinition] = []
        if #available(iOS 18.0, *) {
            types.append(hours(.sleepApneaEvent, "Уведомления о нарушениях дыхания во сне", "count"))
        }
        if #available(iOS 26.2, *) {
            types.append(hours(.hypertensionEvent, "Уведомления о гипертонии", "count"))
        }
        return types
    }

    /// A category type the server folds into hours: minutes of a session (`min`) or one
    /// count per notification, stand hour or symptom (`count`).
    private static func hours(
        _ identifier: HKCategoryTypeIdentifier, _ displayName: String, _ serverUnit: String
    ) -> HealthCategoryDefinition {
        HealthCategoryDefinition(
            typeIdentifier: identifier, displayName: displayName,
            serverKind: hourlyKind, serverUnit: serverUnit, lead: 0
        )
    }
}
