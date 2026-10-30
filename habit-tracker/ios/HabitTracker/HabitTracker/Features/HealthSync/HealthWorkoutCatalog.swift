// [review:need-review] PHASE-02/70
// summary: the workout type as one more type of the pump's set (its identifier for the permission sheet and the sync log, its HKObjectType for the authorization and for a background observer) and the snake_case name of every activity type the server labels, `other` for the rest
import Foundation
import HealthKit

/// The workout type. It sits beside the quantity and category catalogues in the pump's
/// set of types, so one permission sheet, one status check and one background observer
/// (#133) cover it like any other.
enum HealthWorkoutCatalog {
    /// What the sync log and the permission request call it.
    static let identifier = HKObjectType.workoutType().identifier
    static let displayName = "Тренировки"
    static var objectType: HKObjectType { HKObjectType.workoutType() }
}

/// `HKWorkoutActivityType` has no stable string of its own. The names here are the keys
/// of the server's label table (`app/health/workouts.py`); a type not listed goes as
/// `other` and still arrives as a workout.
enum HealthWorkoutActivity {
    static let other = "other"

    // swiftlint:disable:next cyclomatic_complexity function_body_length
    static func name(of type: HKWorkoutActivityType) -> String {
        switch type {
        case .running: return "running"
        case .walking: return "walking"
        case .hiking: return "hiking"
        case .cycling: return "cycling"
        case .swimming: return "swimming"
        case .rowing: return "rowing"
        case .elliptical: return "elliptical"
        case .stairClimbing: return "stair_climbing"
        case .traditionalStrengthTraining: return "traditional_strength_training"
        case .functionalStrengthTraining: return "functional_strength_training"
        case .coreTraining: return "core_training"
        case .highIntensityIntervalTraining: return "high_intensity_interval_training"
        case .crossTraining: return "cross_training"
        case .yoga: return "yoga"
        case .pilates: return "pilates"
        case .cardioDance, .socialDance: return "dance"
        case .cooldown: return "cooldown"
        case .flexibility: return "flexibility"
        case .mixedCardio: return "mixed_cardio"
        case .jumpRope: return "jump_rope"
        case .kickboxing: return "kickboxing"
        case .boxing: return "boxing"
        case .martialArts: return "martial_arts"
        case .tennis: return "tennis"
        case .tableTennis: return "table_tennis"
        case .badminton: return "badminton"
        case .squash: return "squash"
        case .soccer: return "soccer"
        case .basketball: return "basketball"
        case .volleyball: return "volleyball"
        case .golf: return "golf"
        case .skatingSports: return "skating_sports"
        case .downhillSkiing: return "downhill_skiing"
        case .crossCountrySkiing: return "cross_country_skiing"
        case .snowboarding: return "snowboarding"
        case .climbing: return "climbing"
        case .paddleSports: return "paddle_sports"
        case .surfingSports: return "surfing_sports"
        case .wheelchairWalkPace: return "wheelchair_walk_pace"
        case .wheelchairRunPace: return "wheelchair_run_pace"
        default: return other
        }
    }
}
