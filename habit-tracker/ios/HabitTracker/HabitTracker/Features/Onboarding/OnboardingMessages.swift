// [review:need-review] PHASE-01/267
// summary: the words of the Onboarding screen's failures — connection and server errors for every call, and what the server's refusal of the plan (400/422) and a switched-off model (503/502) mean for the person
import Foundation

enum OnboardingMessages {
    static let notConfigured = "Укажите адрес сервера в More → Settings"
    static let templatesFailed = "Не удалось загрузить шаблоны"
    static let templatesApplyFailed = "Не удалось добавить шаблоны"
    static let draftFailed = "Не удалось построить план"
    static let planApplyFailed = "Не удалось создать категории"

    static func base(_ error: APIClientError) -> String {
        switch error {
        case .invalidBaseURL: return "Неверный адрес сервера"
        case .unauthorized: return "Неверный ключ API (401)"
        case .timeout: return "Сервер не ответил вовремя"
        case .transport: return "Нет связи с сервером"
        case .unexpectedStatus(let status): return "Сервер ответил ошибкой \(status)"
        case .invalidResponse: return "Сервер вернул непонятный ответ"
        }
    }

    /// 503: no model is switched on at the server. 502: the model itself failed.
    static func draft(_ error: APIClientError) -> String {
        guard case .unexpectedStatus(let status) = error else { return base(error) }
        switch status {
        case 503: return "На сервере не включён ИИ. Возьмите шаблоны выше или создайте категории вручную."
        case 502: return "Модель не ответила. Повторите."
        default: return base(error)
        }
    }

    /// 400: a name is taken (in the base or twice in the plan) or a field has no category.
    /// 422: the server's own check of the shape failed.
    static func planApply(_ error: APIClientError) -> String {
        guard case .unexpectedStatus(let status) = error else { return base(error) }
        switch status {
        case 400: return "Сервер отклонил план: имя категории уже занято. Измените имя и повторите."
        case 422: return "Сервер отклонил план: проверьте имена и поля."
        default: return base(error)
        }
    }
}
