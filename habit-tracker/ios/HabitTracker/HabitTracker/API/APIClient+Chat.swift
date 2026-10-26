// [review:need-review] PHASE-01/212
// summary: chat endpoints — conversation list/create/read/reset/delete, plan read/apply/dismiss, and one turn as an AsyncThrowingStream of SSE events read with URLSession.bytes (cancelled with the consuming task)
import Foundation

/// API surface needed by the Chat screen; `APIClient` is the production implementation.
protocol ChatAPI {
    func fetchConversations(limit: Int) async throws -> [ChatConversationDTO]
    func createConversation() async throws -> ChatConversationDTO
    func fetchConversation(id: Int) async throws -> ChatConversationDetailDTO
    func resetConversation(id: Int) async throws -> ChatResetDTO
    func deleteConversation(id: Int) async throws
    func fetchPlan(id: Int) async throws -> ChatPlanDTO
    func applyPlan(
        id: Int, selection: ChatPlanSelectionDTO, idempotencyKey: String
    ) async throws -> ChatPlanApplyResultDTO
    func dismissPlan(id: Int) async throws
    /// One turn: the person's message in, the model's answer out as events. The stream
    /// ends when the server closes it; cancelling the consuming task closes the
    /// connection, and the server stores what it had as `interrupted`.
    func streamMessage(conversationID: Int, content: String) -> AsyncThrowingStream<ChatStreamEvent, Error>
}

/// The server refused a turn before the stream began.
///
/// `409` — the conversation still has a running turn (no code in the body), `429` —
/// no free slot (`chat_slots_busy`), `502`/`503` — the model backend is down.
struct ChatTurnRefusal: Error, Equatable {
    let status: Int
    let code: String?
}

extension APIClient: ChatAPI {
    /// A turn can wait for the model's first word far longer than a JSON request; the
    /// server bounds it with its own `first_delta_timeout` and `turn_timeout`.
    static let chatStreamTimeout: TimeInterval = 120
    private static let refusalBodyLimit = 4096

    func fetchConversations(limit: Int) async throws -> [ChatConversationDTO] {
        try await getJSON(
            path: "/chat/conversations",
            query: [URLQueryItem(name: "limit", value: String(limit))]
        )
    }

    func createConversation() async throws -> ChatConversationDTO {
        try await sendJSON(path: "/chat/conversations", method: "POST", body: ChatEmptyBody())
    }

    func fetchConversation(id: Int) async throws -> ChatConversationDetailDTO {
        try await getJSON(path: "/chat/conversations/\(id)", query: [])
    }

    func resetConversation(id: Int) async throws -> ChatResetDTO {
        try await sendJSON(
            path: "/chat/conversations/\(id)/reset", method: "POST", body: ChatEmptyBody()
        )
    }

    func deleteConversation(id: Int) async throws {
        let url = try makeAPIURL(path: "/chat/conversations/\(id)", query: [])
        _ = try await send(makeRequest(url: url, method: "DELETE"))
    }

    func fetchPlan(id: Int) async throws -> ChatPlanDTO {
        try await getJSON(path: "/chat/plans/\(id)", query: [])
    }

    func applyPlan(
        id: Int, selection: ChatPlanSelectionDTO, idempotencyKey: String
    ) async throws -> ChatPlanApplyResultDTO {
        try await sendJSON(
            path: "/chat/plans/\(id)/apply", method: "POST", body: selection,
            idempotencyKey: idempotencyKey
        )
    }

    func dismissPlan(id: Int) async throws {
        let url = try makeAPIURL(path: "/chat/plans/\(id)/dismiss", query: [])
        _ = try await send(makeRequest(url: url, method: "POST"))
    }

    func streamMessage(
        conversationID: Int, content: String
    ) -> AsyncThrowingStream<ChatStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    try await self.readTurn(conversationID: conversationID, content: content) {
                        continuation.yield($0)
                    }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch let error as URLError where error.code == .cancelled {
                    continuation.finish()
                } catch let error as URLError where error.code == .timedOut {
                    continuation.finish(throwing: APIClientError.timeout)
                } catch let error as URLError {
                    continuation.finish(throwing: APIClientError.transport(code: error.errorCode))
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    private func readTurn(
        conversationID: Int, content: String, onEvent: (ChatStreamEvent) -> Void
    ) async throws {
        let url = try makeAPIURL(path: "/chat/conversations/\(conversationID)/messages", query: [])
        var request = makeRequest(url: url, method: "POST")
        request.timeoutInterval = Self.chatStreamTimeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.httpBody = try APIJSONCoding.makeEncoder().encode(ChatMessageCreateDTO(content: content))

        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIClientError.invalidResponse
        }
        guard (200...299).contains(http.statusCode) else {
            throw try await refusal(status: http.statusCode, body: bytes)
        }

        // Feeding the parser at every line end keeps the answer as live as the server
        // sends it; `bytes` itself yields single bytes, so there is no chunk to wait for.
        var parser = SSEParser()
        var line = Data()
        for try await byte in bytes {
            line.append(byte)
            guard byte == 0x0A else { continue }
            for frame in parser.push(line) {
                if let event = ChatStreamEvent(frame: frame) { onEvent(event) }
            }
            line.removeAll(keepingCapacity: true)
        }
        for frame in parser.push(line) + parser.flush() {
            if let event = ChatStreamEvent(frame: frame) { onEvent(event) }
        }
    }

    /// Maps a non-2xx answer to an error; the body of a refusal is `{"detail": "<code>"}`.
    private func refusal(
        status: Int, body: URLSession.AsyncBytes
    ) async throws -> Error {
        if status == 401 { return APIClientError.unauthorized }
        var data = Data()
        for try await byte in body {
            data.append(byte)
            if data.count >= Self.refusalBodyLimit { break }
        }
        let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]
        return ChatTurnRefusal(status: status, code: detail as? String)
    }
}

/// `{}` for POSTs whose body the server ignores (`create`, `reset`).
private struct ChatEmptyBody: Encodable {}
