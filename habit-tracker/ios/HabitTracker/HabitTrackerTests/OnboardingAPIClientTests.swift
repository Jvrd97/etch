// [review:need-review] PHASE-01/267
// summary: wire tests of the Onboarding endpoints — the catalog as the server shapes it, the template apply body and its answer, the plan decoded by its `op` tag (both kinds), and the batch body that echoes the ticked operations with the edited name and the `op` tag in snake_case
import XCTest
@testable import HabitTracker

final class OnboardingAPIClientTests: XCTestCase {
    private var client: APIClient!
    private var captured: URLRequest?
    private var capturedBody: Data?

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
            self.capturedBody = request.httpBody ?? request.httpBodyStream.map { stream in
                stream.open()
                defer { stream.close() }
                var data = Data()
                var buffer = [UInt8](repeating: 0, count: 4096)
                while stream.hasBytesAvailable {
                    let count = stream.read(&buffer, maxLength: buffer.count)
                    if count <= 0 { break }
                    data.append(buffer, count: count)
                }
                return data
            }
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
            return (response, Data(body.utf8))
        }
    }

    private func sentJSON() throws -> [String: Any] {
        let data = try XCTUnwrap(capturedBody)
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    private let catalog = """
    [{"key": "sleep", "name": "Сон", "description": "Часы и качество", "color": "#60A5FA",
      "display_mode": "form", "streak_mode": "build", "group": null,
      "fields": [{"name": "Часы", "field_type": "number", "is_required": true, "default_value": null, "options": null, "order": 0}],
      "added": false},
     {"key": "water", "name": "Вода", "description": null, "color": null,
      "display_mode": "form", "streak_mode": "build", "group": "Тело", "fields": [], "added": true}]
    """

    func testTemplatesReadTheCatalogAndTheAddedFlag() async throws {
        respond(catalog)
        let templates = try await client.fetchTemplates()
        XCTAssertEqual(captured?.url?.path, "/api/v1/categories/templates")
        XCTAssertEqual(captured?.httpMethod, "GET")
        XCTAssertEqual(templates.map(\.key), ["sleep", "water"])
        XCTAssertEqual(templates[0].fields.first?.fieldType, .number)
        XCTAssertFalse(templates[0].added)
        XCTAssertTrue(templates[1].added)
        XCTAssertEqual(templates[1].group, "Тело")
    }

    func testApplyTemplatesSendsKeysAndReadsSkipped() async throws {
        respond(#"{"categories": [{"id": 7, "name": "Сон", "icon": null, "color": null, "display_mode": "form", "streak_mode": "build", "is_active": true, "fields": []}], "skipped": ["water"]}"#, status: 201)
        let result = try await client.applyTemplates(keys: ["sleep", "water"])
        XCTAssertEqual(captured?.url?.path, "/api/v1/categories/templates/apply")
        XCTAssertEqual(captured?.httpMethod, "POST")
        XCTAssertEqual(try sentJSON()["keys"] as? [String], ["sleep", "water"])
        XCTAssertEqual(result.categories.map(\.name), ["Сон"])
        XCTAssertEqual(result.skipped, ["water"])
    }

    private let plan = """
    {"operations": [
      {"op": "create_category", "name": "Сон", "description": null, "icon": null, "color": "#60A5FA",
       "display_mode": "form", "streak_mode": "build", "group": "Тело", "name_conflict": true,
       "fields": [{"name": "Часы", "field_type": "number", "is_required": true, "options": null, "order": 0}]},
      {"op": "add_field", "category_id": 4,
       "field": {"name": "Качество", "field_type": "select", "is_required": false, "options": "[\\"хорошо\\",\\"плохо\\"]", "order": 1}}
    ]}
    """

    func testDraftDecodesBothKindsOfOperationByTheirTag() async throws {
        respond(plan)
        let draft = try await client.draftPlan(transcript: "хочу трекать сон")
        XCTAssertEqual(captured?.url?.path, "/api/v1/onboarding/draft")
        XCTAssertEqual(try sentJSON()["transcript"] as? String, "хочу трекать сон")
        guard case .createCategory(let create) = draft.operations[0],
              case .addField(let add) = draft.operations[1] else { return XCTFail("wrong kinds") }
        XCTAssertTrue(create.nameConflict)
        XCTAssertEqual(create.fields.first?.fieldType, "number")
        XCTAssertEqual(add.categoryId, 4)
        XCTAssertEqual(add.field.options, "[\"хорошо\",\"плохо\"]")
    }

    func testUnknownOperationTagFailsTheWholePlanInsteadOfDroppingARow() async {
        respond(#"{"operations": [{"op": "delete_category", "category_id": 1}]}"#)
        do {
            _ = try await client.draftPlan(transcript: "x")
            XCTFail("expected a decode failure")
        } catch {
            XCTAssertEqual(error as? APIClientError, .invalidResponse)
        }
    }

    func testBatchEchoesTheOperationsWithTheirTagInSnakeCase() async throws {
        respond(#"{"categories": [], "fields": []}"#, status: 201)
        let create = CreateCategoryOpDTO(
            name: "Сон ночной", description: nil, icon: nil, color: nil, displayMode: "form", streakMode: "build",
            group: nil, fields: [PlanFieldDTO(name: "Часы", fieldType: "number", isRequired: true, options: nil, order: 0)],
            nameConflict: false)
        let add = AddFieldOpDTO(categoryId: 4, field: PlanFieldDTO(name: "Качество", fieldType: "text", isRequired: false, options: nil, order: 1))
        _ = try await client.applyPlan([.createCategory(create), .addField(add)])
        XCTAssertEqual(captured?.url?.path, "/api/v1/categories/batch")
        let operations = try XCTUnwrap(try sentJSON()["operations"] as? [[String: Any]])
        XCTAssertEqual(operations.map { $0["op"] as? String }, ["create_category", "add_field"])
        XCTAssertEqual(operations[0]["name"] as? String, "Сон ночной")
        XCTAssertEqual(operations[0]["display_mode"] as? String, "form")
        XCTAssertEqual(operations[0]["name_conflict"] as? Bool, false)
        XCTAssertEqual(operations[1]["category_id"] as? Int, 4)
        XCTAssertEqual((operations[1]["field"] as? [String: Any])?["field_type"] as? String, "text")
    }
}
