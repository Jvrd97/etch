// [review:need-review] PHASE-01/212
// summary: tests for the SSE frame parser and the chat event mapping on recorded streams — chunk splits inside a frame and inside a UTF-8 character, blank lines, several events in one chunk, a cut stream, unknown and malformed frames
import XCTest
@testable import HabitTracker

final class SSEStreamTests: XCTestCase {
    private func parse(_ chunks: [String]) -> [SSEFrame] {
        var parser = SSEParser()
        var frames: [SSEFrame] = []
        for chunk in chunks {
            frames += parser.push(Data(chunk.utf8))
        }
        return frames + parser.flush()
    }

    private func events(_ chunks: [String]) -> [ChatStreamEvent] {
        parse(chunks).compactMap(ChatStreamEvent.init(frame:))
    }

    // MARK: - Frames

    func testSeveralEventsInOneChunkComeOutInOrder() {
        let frames = parse([
            "event: delta\ndata: {\"text\":\"a\"}\n\nevent: delta\ndata: {\"text\":\"b\"}\n\n"
        ])
        XCTAssertEqual(frames.map(\.event), ["delta", "delta"])
        XCTAssertEqual(frames.map(\.data), ["{\"text\":\"a\"}", "{\"text\":\"b\"}"])
    }

    func testFrameSplitAcrossChunksIsEmittedOnceComplete() {
        var parser = SSEParser()
        XCTAssertTrue(parser.push(Data("event: del".utf8)).isEmpty)
        XCTAssertTrue(parser.push(Data("ta\ndata: {\"text\":\"x\"}\n".utf8)).isEmpty)
        let frames = parser.push(Data("\n".utf8))
        XCTAssertEqual(frames, [SSEFrame(event: "delta", data: "{\"text\":\"x\"}")])
    }

    func testBoundaryBetweenTwoChunksSplitsTheDoubleNewline() {
        let frames = parse(["event: done\ndata: {}\n", "\nevent: stop\ndata: {}\n\n"])
        XCTAssertEqual(frames.map(\.event), ["done", "stop"])
    }

    func testMultibyteCharacterSplitAcrossChunksStaysWhole() {
        let frame = Data("event: delta\ndata: {\"text\":\"Привет\"}\n\n".utf8)
        let cut = frame.firstRange(of: Data("и".utf8))!.lowerBound + 1
        var parser = SSEParser()
        var frames = parser.push(frame.subdata(in: 0..<cut))
        frames += parser.push(frame.subdata(in: cut..<frame.count))
        XCTAssertEqual(frames.first?.data, "{\"text\":\"Привет\"}")
    }

    func testBlankLinesAndCommentsBetweenFramesAreSkipped() {
        let frames = parse([
            "\n\n\n: keep-alive\n\nevent: delta\ndata: {\"text\":\"a\"}\n\n\n\n"
        ])
        XCTAssertEqual(frames.map(\.event), ["delta"])
    }

    func testCRLFLineEndingsAreAccepted() {
        let frames = parse(["event: delta\r\ndata: {\"text\":\"a\"}\r\n\r\n"])
        XCTAssertEqual(frames, [SSEFrame(event: "delta", data: "{\"text\":\"a\"}")])
    }

    func testMultipleDataLinesJoinWithNewline() {
        let frames = parse(["event: delta\ndata: one\ndata: two\n\n"])
        XCTAssertEqual(frames.first?.data, "one\ntwo")
    }

    func testFlushReturnsTheLastFrameWhenTheStreamEndsWithoutBlankLine() {
        var parser = SSEParser()
        XCTAssertTrue(parser.push(Data("event: done\ndata: {\"message_id\":1}".utf8)).isEmpty)
        XCTAssertEqual(parser.flush().map(\.event), ["done"])
        XCTAssertTrue(parser.flush().isEmpty, "flush drains the buffer")
    }

    // MARK: - Chat events

    func testChatEventsMapEveryKindTheServerSends() {
        let mapped = events([
            "event: delta\ndata: {\"text\":\"Привет\"}\n\n",
            "event: thinking\ndata: {\"index\":0,\"thinking\":\"\"}\n\n",
            "event: writing\ndata: {\"index\":1}\n\n",
            "event: acting\ndata: {\"index\":2,\"tool\":\"Read\"}\n\n",
            "event: step_end\ndata: {\"index\":2}\n\n",
            "event: retrieval\ndata: {\"query_name\":\"day_card\",\"row_count\":3,\"chars\":120,\"refusal\":null}\n\n",
            "event: usage\ndata: {\"input_tokens\":10,\"output_tokens\":5,\"cache_read_tokens\":null}\n\n",
            "event: stop\ndata: {\"reason\":\"end_turn\"}\n\n",
            "event: done\ndata: {\"message_id\":7,\"seq\":2,\"status\":\"complete\"}\n\n",
        ])
        XCTAssertEqual(mapped, [
            .delta("Привет"),
            .thinking,
            .writing,
            .acting(tool: "Read"),
            .stepEnd,
            .retrieval(queryName: "day_card", rowCount: 3, refusal: nil),
            .usage,
            .stop(reason: "end_turn"),
            .done(messageID: 7, seq: 2, status: "complete"),
        ])
    }

    func testErrorFrameCarriesTheMachineCode() {
        XCTAssertEqual(
            events(["event: error\ndata: {\"code\":\"backend_failed\"}\n\n"]),
            [.error(code: "backend_failed")]
        )
    }

    func testEmptyDeltaUnknownEventAndBrokenJSONProduceNothing() {
        XCTAssertTrue(events([
            "event: delta\ndata: {\"text\":\"\"}\n\n",
            "event: future_thing\ndata: {\"x\":1}\n\n",
            "event: delta\ndata: {\"text\":\"cut\n\n",
            "event: delta\ndata: [1,2]\n\n",
            "data: {\"text\":\"no event name\"}\n\n",
        ]).isEmpty)
    }

    func testDoneWithoutItsFieldsIsDropped() {
        XCTAssertTrue(events(["event: done\ndata: {\"seq\":1}\n\n"]).isEmpty)
    }

    func testCutStreamKeepsEverythingBeforeTheCut() {
        let mapped = events([
            "event: delta\ndata: {\"text\":\"a\"}\n\n",
            "event: delta\ndata: {\"text\":\"b\"}\n\nevent: delta\ndata: {\"te",
        ])
        XCTAssertEqual(mapped, [.delta("a"), .delta("b")])
    }
}
