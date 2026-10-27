// [review:need-review] PHASE-01/212, PHASE-03/230
// summary: tests for the chat endpoints — URLs, decoding of the conversation, message and plan, the apply body and its idempotency key, DELETE 409, and the streamed turn (events in order, refusals 409/429/502, a connection cut mid-answer, cancellation); no real model is called
import XCTest
@testable import HabitTracker

/// Replays a scripted stream: the chunks are delivered one by one, then either the
/// connection closes cleanly or fails with `failure`.
private final class ScriptedStreamProtocol: URLProtocol {
    nonisolated(unsafe) static var status = 200
    nonisolated(unsafe) static var chunks: [Data] = []
    nonisolated(unsafe) static var failure: Error?
    /// Keeps the connection open after the chunks, like a model that went quiet.
    nonisolated(unsafe) static var holdOpen = false

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let response = HTTPURLResponse(
            url: request.url!, statusCode: Self.status, httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "text/event-stream"]
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        for chunk in Self.chunks {
            client?.urlProtocol(self, didLoad: chunk)
        }
        if Self.holdOpen {
            return
        }
        if let failure = Self.failure {
            // Late, like a real cut: the bytes already sent reach the reader before the error.
            DispatchQueue.global().asyncAfter(deadline: .now() + 0.1) {
                self.client?.urlProtocol(self, didFailWithError: failure)
            }
        } else {
            client?.urlProtocolDidFinishLoading(self)
        }
    }

    override func stopLoading() {}

    static func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ScriptedStreamProtocol.self]
        return URLSession(configuration: configuration)
    }

    static func script(status: Int = 200, chunks: [String], failure: Error? = nil) {
        self.status = status
        self.chunks = chunks.map { Data($0.utf8) }
        self.failure = failure
    }
}

final class ChatAPIClientTests: XCTestCase {
    private static let baseURL = URL(string: "http://localhost:8812")!

    override func tearDown() {
        MockURLProtocol.requestHandler = nil
        ScriptedStreamProtocol.script(chunks: [])
        super.tearDown()
    }

    private func makeClient(session: URLSession = MockURLProtocol.makeSession()) -> APIClient {
        APIClient(baseURL: Self.baseURL, apiKeyProvider: { "key" }, session: session)
    }

    private func respond(
        _ request: URLRequest, status: Int = 200, json: String = "{}"
    ) -> (HTTPURLResponse, Data) {
        let response = HTTPURLResponse(
            url: request.url!, statusCode: status, httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )!
        return (response, Data(json.utf8))
    }

    private static let conversationJSON = """
    {"id": 4, "title": null, "started_on": "2026-10-25", "kind": "general",
     "llm_backend": "claude_cli", "context_version": 1, "last_message_at": "2026-10-25T10:00:00",
     "archived": false, "created_at": "2026-10-25T09:00:00",
     "usage": {"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 0,
               "message_count": 6, "latency_ms_median": null}}
    """

    private static let planJSON = """
    {"id": 9, "message_id": 31, "entry_date": "2026-10-25", "status": "proposed",
     "operation_count": 4, "applied_summary_id": null, "applied_at": null,
     "created_at": "2026-10-25T10:00:00",
     "plan": {"entry_date": "2026-10-25",
       "metrics": [{"op": "log_metric", "category_id": 1, "field_id": 2, "value": 30.0,
                    "source_text": "отжался 30 раз", "uncertain": false,
                    "implausible": false, "estimated": false}],
       "checklist": [{"op": "check", "category_id": 3, "field_id": 5,
                      "source_text": "витамины", "uncertain": true}],
       "journal": {"op": "write_journal", "title": null, "content": "Хороший день",
                   "mood": null, "tags": null, "mode": "append"},
       "day_plan": {"op": "rewrite_day_plan", "title": "План",
                    "sections": [{"title": "Утро", "kind": "morning", "items": [
                      {"code": "run", "kind": "task", "rigidity": "soft", "text": "Бег",
                       "window": null, "done_criterion": null, "unlinked_reason": null}]}]}}}
    """

    // MARK: - Conversations

    func testFetchConversationsAsksForTheLimitAndDecodesTheRow() async throws {
        var seen: URLRequest?
        MockURLProtocol.requestHandler = { request in
            seen = request
            return self.respond(request, json: "[\(Self.conversationJSON)]")
        }
        let rows = try await makeClient().fetchConversations(limit: 50)

        XCTAssertEqual(seen?.url?.path, "/api/v1/chat/conversations")
        XCTAssertEqual(seen?.url?.query, "limit=50")
        XCTAssertEqual(rows.first?.id, 4)
        XCTAssertEqual(rows.first?.messageCount, 6)
        XCTAssertNil(rows.first?.title)
    }

    func testFetchConversationDecodesMessagesWithPlanAndRetrievals() async throws {
        let json = """
        {"id": 4, "messages": [
          {"id": 30, "seq": 1, "role": "user", "content": "Привет", "status": "complete",
           "error_code": null, "created_at": "2026-10-25T10:00:00", "plan_id": null,
           "retrievals": []},
          {"id": 31, "seq": 2, "role": "assistant", "content": "Вот план", "status": "complete",
           "error_code": null, "created_at": "2026-10-25T10:00:05", "plan_id": 9,
           "retrievals": [{"id": 1, "query_name": "day_card", "params": {}, "row_count": 3,
                           "chars": 10, "created_at": "2026-10-25T10:00:01"}]}],
         "resume_ready": true}
        """
        MockURLProtocol.requestHandler = { self.respond($0, json: json) }
        let detail = try await makeClient().fetchConversation(id: 4)

        XCTAssertEqual(detail.messages.map(\.seq), [1, 2])
        XCTAssertEqual(detail.messages[1].planId, 9)
        XCTAssertEqual(detail.messages[1].retrievals, [ChatRetrievalDTO(queryName: "day_card", rowCount: 3)])
    }

    func testCreateAndResetPostToTheirPaths() async throws {
        var paths: [String] = []
        MockURLProtocol.requestHandler = { request in
            paths.append("\(request.httpMethod ?? "") \(request.url?.path ?? "")")
            return self.respond(request, json: request.url?.path.hasSuffix("reset") == true
                ? "{\"reset\": 1}" : Self.conversationJSON)
        }
        let client = makeClient()
        _ = try await client.createConversation()
        let reset = try await client.resetConversation(id: 4)

        XCTAssertEqual(paths, ["POST /api/v1/chat/conversations", "POST /api/v1/chat/conversations/4/reset"])
        XCTAssertEqual(reset.reset, 1)
    }

    func testDeleteConversationUsesDELETEAndAcceptsNoContent() async throws {
        var seen: URLRequest?
        MockURLProtocol.requestHandler = { request in
            seen = request
            return self.respond(request, status: 204, json: "")
        }
        try await makeClient().deleteConversation(id: 4)

        XCTAssertEqual(seen?.httpMethod, "DELETE")
        XCTAssertEqual(seen?.url?.path, "/api/v1/chat/conversations/4")
    }

    func testDeleteConversationSurfacesConflictAsStatus409() async {
        MockURLProtocol.requestHandler = { self.respond($0, status: 409, json: "{\"detail\":\"turn 2 is still running\"}") }
        do {
            try await makeClient().deleteConversation(id: 4)
            XCTFail("expected 409")
        } catch {
            XCTAssertEqual(error as? APIClientError, .unexpectedStatus(409))
        }
    }

    // MARK: - Plans

    func testPlanDecodesEveryOperationKind() async throws {
        MockURLProtocol.requestHandler = { self.respond($0, json: Self.planJSON) }
        let plan = try await makeClient().fetchPlan(id: 9)

        XCTAssertEqual(plan.status, ChatPlanDTO.proposedStatus)
        XCTAssertEqual(plan.plan.metrics.first?.value, 30)
        XCTAssertTrue(plan.plan.checklist[0].uncertain)
        XCTAssertEqual(plan.plan.journal?.mode, .append)
        XCTAssertEqual(plan.plan.dayPlan?.isRewrite, true)
        XCTAssertEqual(plan.plan.dayPlan?.itemCount, 1)
    }

    func testApplySendsTheSelectionVerbatimWithTheIdempotencyKey() async throws {
        let plan = try JSONDecoder.chatTest.decode(ChatPlanDTO.self, from: Data(Self.planJSON.utf8))
        var seen: URLRequest?
        var body: [String: Any] = [:]
        MockURLProtocol.requestHandler = { request in
            seen = request
            body = (try? JSONSerialization.jsonObject(with: request.bodyData) as? [String: Any]) ?? [:]
            return self.respond(request, status: 201, json: """
            {"plan": \(Self.planJSON), "entry_ids": [1], "journal_entry_id": null,
             "day_plan_id": null, "applied_operations": 2}
            """)
        }
        let selection = ChatPlanSelectionDTO(
            metrics: plan.plan.metrics, checklist: [], journal: plan.plan.journal, dayPlan: true
        )
        let result = try await makeClient().applyPlan(id: 9, selection: selection, idempotencyKey: "key-1")

        XCTAssertEqual(seen?.url?.path, "/api/v1/chat/plans/9/apply")
        XCTAssertEqual(seen?.value(forHTTPHeaderField: "Idempotency-Key"), "key-1")
        XCTAssertEqual(result.appliedOperations, 2)
        let metrics = body["metrics"] as? [[String: Any]]
        XCTAssertEqual(metrics?.first?["category_id"] as? Int, 1)
        XCTAssertEqual(metrics?.first?["source_text"] as? String, "отжался 30 раз")
        XCTAssertEqual(metrics?.first?["implausible"] as? Bool, false)
        XCTAssertEqual((body["checklist"] as? [Any])?.count, 0)
        XCTAssertEqual((body["journal"] as? [String: Any])?["mode"] as? String, "append")
        XCTAssertEqual(body["day_plan"] as? Bool, true)
    }

    func testDismissPostsAndAcceptsNoContent() async throws {
        var seen: URLRequest?
        MockURLProtocol.requestHandler = { request in
            seen = request
            return self.respond(request, status: 204, json: "")
        }
        try await makeClient().dismissPlan(id: 9)

        XCTAssertEqual(seen?.httpMethod, "POST")
        XCTAssertEqual(seen?.url?.path, "/api/v1/chat/plans/9/dismiss")
    }

    // MARK: - Streamed turn

    private func collect(_ stream: AsyncThrowingStream<ChatStreamEvent, Error>) async throws -> [ChatStreamEvent] {
        var events: [ChatStreamEvent] = []
        for try await event in stream { events.append(event) }
        return events
    }

    func testTurnStreamsEventsInOrderAndSendsTheMessage() async throws {
        ScriptedStreamProtocol.script(chunks: [
            "event: delta\ndata: {\"text\":\"При\"}\n\nevent: del",
            "ta\ndata: {\"text\":\"вет\"}\n\n",
            "event: done\ndata: {\"message_id\":5,\"seq\":2,\"status\":\"complete\"}\n\n",
        ])
        let events = try await collect(
            makeClient(session: ScriptedStreamProtocol.makeSession())
                .streamMessage(conversationID: 4, content: "Привет")
        )

        XCTAssertEqual(events, [
            .delta("При"), .delta("вет"), .done(messageID: 5, seq: 2, status: "complete"),
        ])
    }

    func testTurnRequestIsAPostWithJSONBodyAndAcceptHeader() async throws {
        var seen: URLRequest?
        MockURLProtocol.requestHandler = { request in
            seen = request
            let (response, _) = self.respond(request)
            return (response, Data("event: done\ndata: {\"message_id\":1,\"seq\":2,\"status\":\"complete\"}\n\n".utf8))
        }
        _ = try await collect(makeClient().streamMessage(conversationID: 4, content: "Привет"))

        XCTAssertEqual(seen?.httpMethod, "POST")
        XCTAssertEqual(seen?.url?.path, "/api/v1/chat/conversations/4/messages")
        XCTAssertEqual(seen?.value(forHTTPHeaderField: "Accept"), "text/event-stream")
        XCTAssertEqual(seen?.value(forHTTPHeaderField: "X-API-Key"), "key")
        XCTAssertEqual(seen?.timeoutInterval, APIClient.chatStreamTimeout)
        let body = try JSONSerialization.jsonObject(with: seen?.bodyData ?? Data()) as? [String: Any]
        XCTAssertEqual(body?["content"] as? String, "Привет")
    }

    func testTurnKeepsAnUnterminatedLastFrame() async throws {
        ScriptedStreamProtocol.script(chunks: [
            "event: delta\ndata: {\"text\":\"a\"}\n\nevent: done\ndata: {\"message_id\":5,\"seq\":2,\"status\":\"complete\"}",
        ])
        let events = try await collect(
            makeClient(session: ScriptedStreamProtocol.makeSession())
                .streamMessage(conversationID: 4, content: "x")
        )

        XCTAssertEqual(events.last, .done(messageID: 5, seq: 2, status: "complete"))
    }

    func testRefusalStatusesCarryTheirMachineCode() async {
        let cases: [(Int, String, String?)] = [
            (409, "{\"detail\":\"turn 2 of conversation 4 is still running\"}", "turn 2 of conversation 4 is still running"),
            (429, "{\"detail\":\"chat_slots_busy\"}", "chat_slots_busy"),
            (502, "{\"detail\":\"backend_failed\"}", "backend_failed"),
            (503, "not json", nil),
        ]
        for (status, body, code) in cases {
            ScriptedStreamProtocol.script(status: status, chunks: [body])
            do {
                _ = try await collect(
                    makeClient(session: ScriptedStreamProtocol.makeSession())
                        .streamMessage(conversationID: 4, content: "x")
                )
                XCTFail("expected a refusal for \(status)")
            } catch {
                XCTAssertEqual(error as? ChatTurnRefusal, ChatTurnRefusal(status: status, code: code))
            }
        }
    }

    func testUnauthorizedTurnIsATypedError() async {
        ScriptedStreamProtocol.script(status: 401, chunks: ["{}"])
        do {
            _ = try await collect(
                makeClient(session: ScriptedStreamProtocol.makeSession())
                    .streamMessage(conversationID: 4, content: "x")
            )
            XCTFail("expected 401")
        } catch {
            XCTAssertEqual(error as? APIClientError, .unauthorized)
        }
    }

    func testCutConnectionDeliversEarlierEventsThenThrowsTransport() async {
        ScriptedStreamProtocol.script(
            chunks: ["event: delta\ndata: {\"text\":\"a\"}\n\nevent: delta\ndata: {\"te"],
            failure: URLError(.networkConnectionLost)
        )
        var events: [ChatStreamEvent] = []
        do {
            for try await event in makeClient(session: ScriptedStreamProtocol.makeSession())
                .streamMessage(conversationID: 4, content: "x") {
                events.append(event)
            }
            XCTFail("expected a transport error")
        } catch {
            XCTAssertEqual(error as? APIClientError, .transport(code: URLError.networkConnectionLost.rawValue))
        }
        XCTAssertEqual(events, [.delta("a")])
    }

    func testCancellingTheConsumerEndsTheStreamWithoutAnError() async throws {
        // A stream that never closes: the head of the answer arrives, then silence.
        ScriptedStreamProtocol.script(chunks: ["event: delta\ndata: {\"text\":\"a\"}\n\n"])
        ScriptedStreamProtocol.holdOpen = true
        defer { ScriptedStreamProtocol.holdOpen = false }
        let stream = makeClient(session: ScriptedStreamProtocol.makeSession())
            .streamMessage(conversationID: 4, content: "x")
        let consumer = Task { () -> [ChatStreamEvent] in
            var events: [ChatStreamEvent] = []
            for try await event in stream {
                events.append(event)
                if events.count == 1 { withUnsafeCurrentTask { $0?.cancel() } }
            }
            return events
        }
        let events = try await consumer.value

        XCTAssertEqual(events, [.delta("a")])
    }
}

private extension JSONDecoder {
    static var chatTest: JSONDecoder { APIJSONCoding.makeDecoder() }
}

private extension URLRequest {
    /// `httpBody` is moved into `httpBodyStream` by URLSession before a URLProtocol sees it.
    var bodyData: Data {
        if let httpBody { return httpBody }
        guard let stream = httpBodyStream else { return Data() }
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
}
