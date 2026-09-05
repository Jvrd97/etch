---
name: architecture-grill
description: "Architecture-level grilling that produces system/container/component design through Socratic dialogue. Use when designing or redesigning systems that touch multiple services, defining service boundaries, or resolving cross-cutting concerns. Differs from /grill-me (per-service PRD) — focuses on bounded contexts, ownership, transports, and trade-offs. Triggers on: redesign architecture, design new system, define service boundaries, decompose monolith, cross-service workflow."
---

# Architecture Grilling

Architecture-level alignment session. Use this BEFORE per-service `/grill-me` when the question is "how should the system look" not "how should this service work".

## When to use this vs `/grill-me` (per-service)

| Question type | Tool |
|---|---|
| "How should connector-service handle wearables?" | `/grill-me` (single service) |
| "Should we split connector into connector + clinic?" | `/grill-me-arch` (architectural split) |
| "What API does ingest endpoint expose?" | `/grill-me` |
| "How do services communicate across the platform?" | `/grill-me-arch` |
| "What fields does User model need?" | `/grill-me` |
| "Who owns user data — auth or profile service?" | `/grill-me-arch` |

Rule of thumb: if the answer changes contracts between 2+ services, it's architectural.

## Use `software-architect` agent

This grilling uses the `software-architect` sub-agent, not the generic `/grill-me`. The agent has:
- DDD vocabulary (bounded contexts, aggregates)
- Trade-off framework
- C4 model fluency
- Pattern catalog with failure modes

## Process

### Pre-grilling checklist (before starting)

Verify you have:
- A specific architectural question or change in mind (not "let's design something")
- Read access to current state if exists: `docs/current/architecture/`, existing service READMEs
- A clear "out of scope" — what you're NOT deciding this session
- 2-3 hour block (or willingness to split across sessions)

If you don't have these — STOP and do `/triage` first to scope the work.

### Phase 1 — Domain Discovery (10-20 questions)

Before any technology talk:

- What business problem is this addressing?
- What user-visible behaviors change?
- What does the domain language sound like? (Listen for nouns / verbs that recur)
- Where are the current pain points in domain modeling?
- What's the bounded context boundary?

Output of phase: list of bounded contexts + key domain events, NOT yet services.

### Phase 2 — Service decomposition (15-25 questions)

Now move from contexts to services:

- For each context, is it one service or multiple?
- Why these boundaries and not others? (Force trade-off articulation)
- What happens at each boundary? (API? events? shared DB?)
- Are there services with no clear context — and should they exist?
- Are there services that don't fit cleanly into one context (cross-cutting)?

Forbidden answers from user (push back if you hear):
- "Microservices because best practice"
- "It might be useful later"
- "Some teams do it this way"

Demanded answers:
- Concrete failure mode this avoids
- Concrete capability this enables
- Trade-off explicitly stated

### Phase 3 — Data ownership (10-15 questions)

For each significant entity:

- Which service is the source of truth?
- Who else reads it? How? (API call vs event consumption vs replicated)
- What's the consistency model? (strong vs eventual vs read-your-writes)
- What happens if ownership service is down?
- How does referential integrity work across services?

Output: ownership table (entity → owner → readers → consistency).

### Phase 4 — Transports and contracts (15-20 questions)

For each service-to-service interaction:

- Synchronous (HTTP/gRPC) or asynchronous (queue/events)?
- Justify: what does sync give us? What does async cost us?
- What's the retry policy? Idempotency strategy?
- What's the failure mode? (Timeout? Cascade? Circuit breaker?)
- What's the latency budget? Throughput requirement?

This is where outbox pattern, sagas, CQRS questions arise. Don't introduce patterns until requirement forces them.

### Phase 5 — Cross-cutting concerns (10-15 questions)

Verify each is addressed:

- Authentication: how do services trust each other? How do users authenticate?
- Authorization: where is authz checked? Centralized vs decentralized?
- Observability: tracing, logging, metrics — what standards across services?
- Schema evolution: how do API contracts evolve? Versioning?
- Multi-tenancy: if applicable, how is tenant isolation enforced?
- PII / compliance: who can hold what data? Retention?

### Phase 6 — Evolution and trade-offs (5-10 questions)

Force forward thinking:

- What's hardest to change in this design? (Architecture is what's hardest to change.)
- What's easy to change later?
- Where will we feel pain in 6 months? Why is it worth it?
- What pattern are we deliberately NOT using, and why?
- If we had to rewrite tomorrow, what would we keep / drop?

## Diagram requirements

During grilling, after each major decision — DRAW IT immediately in Mermaid C4 syntax. Don't wait for `/write-architecture`. The diagram surfaces issues the prose hides.

Use `c4-diagrams` skill for syntax.

After Phase 2 — interim C4Container diagram
After Phase 3 — interim ownership table
After Phase 4 — sequence diagrams for key flows
After Phase 5 — list of cross-cutting concerns with where they're handled

## Pre-decisions

Before grilling starts, resolve these (or AI will get stuck):

- **Naming**: if creating new services, agree on names BEFORE grilling boundaries
- **Stack**: which technologies are on the table? (HTTPX vs Kafka, Postgres vs Mongo)
- **Constraints**: team size, latency requirements, compliance scope
- **Hard non-goals**: what's explicitly out of scope for this design?

If user can't pre-decide — first session is `/explain-and-record` on the open question, then come back to architecture grilling.

## Output

End of grilling produces in `brain-dumps/architecture/<date>-<topic>-arch-grill.md`:

```markdown
# Architecture Grilling: <Topic> — <Date>

## Domain
- Bounded contexts: ...
- Domain events: ...

## Services proposed
| Service | Owns | Reads | Justification |
|---|---|---|---|
| ... | ... | ... | ... |

## Transports decided
| From → To | Type | Justification | Failure mode |
|---|---|---|---|
| ... | ... | ... | ... |

## Cross-cutting decisions
- Auth: ...
- Observability: ...
- ...

## Trade-offs explicitly accepted
- We chose X over Y because Z
- We accept cost C in exchange for benefit B

## Pre-decisions for ADRs (to write in /write-architecture)
- ADR: <topic> — context, options, decision

## Open questions for next session
- ...

## Diagrams sketched (will be cleaned up in /write-architecture)
[Mermaid blocks]
```

This is the **input** to `/write-architecture`. Don't try to make it polished — it's a grilling artifact, not deliverable.

## Anti-patterns during grilling

- ❌ Letting user say "let me think about it" without timeboxing
- ❌ Drawing diagrams before discussing what they represent
- ❌ Accepting pattern names without justification ("we'll use saga")
- ❌ Skipping "what fails?" questions
- ❌ Designing for hypothetical future scale without concrete number
- ❌ One-option decisions (always present alternatives)
- ❌ Grilling implementation details (those belong in per-service `/grill-me`)
