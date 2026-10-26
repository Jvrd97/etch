// [review:need-review] PHASE-01/212
// summary: incremental Server-Sent Events parser over raw bytes — frames are split on a blank line wherever a network chunk ended, CRLF accepted, comments and empty frames skipped, the unterminated tail returned by flush()
import Foundation

/// One `event:` / `data:` block of a Server-Sent Events stream.
struct SSEFrame: Equatable {
    let event: String?
    let data: String
}

/// Stateful reader of an SSE byte stream.
///
/// A network chunk ends wherever TCP decided: in the middle of a frame, and in the
/// middle of a UTF-8 character. The parser keeps the leftover as bytes and decodes
/// only complete frames. A frame boundary is an ASCII blank line, so a multi-byte
/// character is never cut by the split.
struct SSEParser {
    private static let lineFeed: UInt8 = 0x0A
    private static let carriageReturn: UInt8 = 0x0D
    private static let frameSeparator = Data([lineFeed, lineFeed])

    private var buffer = Data()

    /// Frames completed by this chunk, in arrival order.
    mutating func push(_ chunk: Data) -> [SSEFrame] {
        // CRLF streams: dropping CR turns `\r\n\r\n` into the `\n\n` boundary. A raw CR
        // cannot occur inside a JSON payload (it is escaped as `\r`), so nothing is lost.
        buffer.append(chunk.filter { $0 != Self.carriageReturn })
        var frames: [SSEFrame] = []
        while let boundary = buffer.firstRange(of: Self.frameSeparator) {
            let block = Data(buffer[buffer.startIndex..<boundary.lowerBound])
            buffer.removeSubrange(buffer.startIndex..<boundary.upperBound)
            if let frame = Self.frame(from: block) {
                frames.append(frame)
            }
        }
        return frames
    }

    /// The last frame when the stream ended without its closing blank line.
    ///
    /// A connection cut mid-turn leaves exactly this; dropping it would lose the
    /// final `done` of a turn that did finish.
    mutating func flush() -> [SSEFrame] {
        let rest = buffer
        buffer.removeAll()
        guard let frame = Self.frame(from: rest) else { return [] }
        return [frame]
    }

    private static func frame(from block: Data) -> SSEFrame? {
        guard let text = String(data: block, encoding: .utf8) else { return nil }
        var event: String?
        var data: [String] = []
        for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
            if line.hasPrefix(":") { continue }
            if let value = value(of: line, field: "event") {
                event = value
            } else if let value = value(of: line, field: "data") {
                data.append(value)
            }
        }
        guard event != nil || !data.isEmpty else { return nil }
        return SSEFrame(event: event, data: data.joined(separator: "\n"))
    }

    /// `field: value` with the single optional space after the colon removed.
    private static func value(of line: Substring, field: String) -> String? {
        let prefix = field + ":"
        guard line.hasPrefix(prefix) else { return nil }
        let rest = line.dropFirst(prefix.count)
        return String(rest.hasPrefix(" ") ? rest.dropFirst() : rest)
    }
}
