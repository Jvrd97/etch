---
name: write-architecture
description: "Generate the structured set of architecture documents from a completed architecture grilling session. Use after /grill-me-arch when alignment is reached. Produces system-context, container-diagram, component-diagrams, data-flow, data-model, ADRs, and glossary as separate files. Each file answers ONE question."
---

# Write Architecture (post-grilling)

After `/grill-me-arch` is complete and alignment exists, generate the structured architecture documentation set.

## Pre-conditions

Before invoking this:
- An architecture grilling session has happened (in this conversation or recent ones)
- Brain dump artifact exists in `brain-dumps/architecture/<date>-<topic>-arch-grill.md` OR equivalent context
- User has explicitly said "ready to write architecture"

If grilling is not done — STOP and tell user to run `/grill-me-arch` first.

## Output structure

Generate **a graph of related documents**, not one mega-file.

> **Where this writes (phase-aware)**: architecture docs go under `docs/current/architecture/`.
> `current` is a symlink to the active phase (e.g. `PHASE-00`); the canonical phase marker is
> `docs/ROADMAP/STATUS.md` (`current: PHASE-NN`). Resolve through `current` — never hardcode `PHASE-NN`.
> ADRs go under `docs/` (by phase + lifecycle status): phase-scoped → `docs/<PHASE-NN>/ADRs/`, cross-phase → `docs/GENERAL/ADRs/`.

```
docs/current/architecture/          # current = symlink to active phase
├── README.md                       # Index + how to navigate
├── system-context.md               # L1: external view (REQUIRED)
├── container-diagram.md            # L2: service-level view (REQUIRED)
├── component-diagrams/             # L3: inside specific services (OPTIONAL)
│   ├── medical-service.md
│   └── ai-service.md
├── data-flow/                      # Sequence diagrams (REQUIRED for key flows)
│   ├── user-onboarding.md
│   ├── wearable-ingest.md
│   └── voice-input.md
├── data-model.md                   # Entity ownership (REQUIRED)
├── cross-cutting.md                # Auth, observability, etc (REQUIRED)
└── glossary.md                     # Domain terms (REQUIRED)

docs/<PHASE-NN>/ADRs/                 # ADRs live under docs/, by phase + lifecycle status
├── <status>/ADR-NNN-<slug>.md            # One ADR per major decision (REQUIRED for cross-service decisions)
└── ...
# cross-phase / platform-wide decisions → docs/GENERAL/ADRs/
```

## File templates

### README.md (architecture index)

```markdown
# Architecture Documentation

> Last reviewed: <date>
> Reviewer: <user>

## Read this first
This folder describes how the Alvion platform is structured.

## Navigation

### High-level (start here)
- [`system-context.md`](system-context.md) — What's inside the platform, what's outside (C4 L1)
- [`container-diagram.md`](container-diagram.md) — Services and their interactions (C4 L2)

### Deep dives
- [`component-diagrams/`](component-diagrams/) — Inside individual services (C4 L3)
- [`data-flow/`](data-flow/) — Sequence diagrams of key user flows
- [`data-model.md`](data-model.md) — Who owns what entity

### Decisions and context
- [`docs/<PHASE-NN>/ADRs/`](../../../docs/<PHASE-NN>/ADRs/) — Why we chose what we chose (cross-phase: `docs/GENERAL/ADRs/`)
- [`cross-cutting.md`](cross-cutting.md) — Auth, observability, multi-tenancy
- [`glossary.md`](glossary.md) — Domain terminology

## How to update this
- New service → add to `container-diagram.md`, optionally `component-diagrams/`
- New decision affecting 2+ services → new ADR in `docs/<PHASE-NN>/ADRs/` (cross-phase: `docs/GENERAL/ADRs/`)
- New domain term → glossary
- Major redesign → `/grill-me-arch` first, then update everything
```

### system-context.md (L1)

```markdown
# System Context

> C4 Level 1: Alvion platform + external world.
> See [`container-diagram.md`](container-diagram.md) for what's inside.

## Diagram

[Mermaid C4Context block from c4-diagrams skill]

## Actors
- **User**: ...
- **Partner Clinic Staff**: ...
- (etc)

## External systems
- **Apple Health**: pulled metrics, OAuth flow
- **Whoop**: ...
- (etc)

## What's inside (one-line)
The Alvion platform is a personal health data hub that:
- Ingests wearable + manual data
- Computes wellness scores
- Provides AI-driven recommendations
- Coordinates with partner clinics (Phase 1)

## Boundaries
- **Compliance**: GDPR-like principles applied; no HIPAA scope claimed (yet)
- **Data residency**: <if applicable>
```

### container-diagram.md (L2)

```markdown
# Container Diagram

> C4 Level 2: All services and data stores.
> For external view, see [`system-context.md`](system-context.md).
> For individual service internals, see [`component-diagrams/`](component-diagrams/).

## Diagram

[Mermaid C4Container block]

## Services

| Service | Capability | Owns | Calls | Called by |
|---|---|---|---|---|
| Gateway | Routing + auth | nothing | all internal | external |
| Medical | User metrics + score | metrics, allergies, conditions | postgres, redis | gateway, ai, connector |
| Connector | Wearables ingest | nothing | medical | external wearables (pull) |
| AI | LLM orchestration | nothing | medical, openai | gateway |
| ... | | | | |

## Data stores

| Store | Tech | What it holds | Owners |
|---|---|---|---|
| PostgreSQL | asyncpg | Transactional user data | medical, payment, subscription |
| Redis | Redis 7 | Context cache, sessions | medical, ai, gateway |
| Qdrant | Qdrant | Medical knowledge embeddings | ai (writes), ai (reads) |

## Frozen / planned
- **Frozen**: telehealth, supplement, order (return 503 in MVP, kept for future)
- **Planned (Phase 1)**: clinic-service (partner clinics, QR flows)
```

### data-model.md

```markdown
# Data Model

> Entity ownership and access patterns.

## Ownership rules
1. Each entity has exactly ONE service that writes it (source of truth).
2. Other services read via:
   - API call to owner (sync, current state)
   - Event subscription (eventual consistency)
   - Local cache populated from API/events
3. Cross-service references via ID only, never embedded objects.

## Entities

| Entity | Owner | Readers | Access pattern | Consistency |
|---|---|---|---|---|
| User | identity-service | all | API call cached 5min | strong on write, eventual on read |
| UserMetrics | medical | ai, gamification | API call | strong |
| UserContext (computed) | medical | ai | Redis cache 5min | eventual (TTL invalidation) |
| Achievement | gamification | ai | API call | strong |
| Subscription | subscription | gamification, payment | API call | strong |
| ChatHistory | ai | (none) | local | strong (own service) |

## Schemas (high level)
For full schemas, see per-service docs in `services/<name>/schemas/`.

## ER Diagram (high-level only)

[Mermaid erDiagram showing core entities, not full schemas]
```

### data-flow/<name>.md (sequence diagrams)

```markdown
# Flow: <name>

> Sequence diagram for <description>.

## Pre-conditions
- ...

## Happy path

[Mermaid sequenceDiagram]

## Failure modes

### If medical-service is down
- Connector retries 3x with exponential backoff
- After 3 fails: pushes to local outbox queue
- Returns 202 to wearable API (will retry async)
- Background job drains outbox when medical returns

### If user has no data yet (cold start)
- Medical returns empty UserContext
- AI handles empty context gracefully (no embedding lookup, default prompt)

## Latency budget
| Step | Budget | Actual (measured) |
|---|---|---|
| Auth check | 50ms | TBD |
| Ingest write | 100ms | TBD |
| Total | 500ms p99 | TBD |
```

### cross-cutting.md

```markdown
# Cross-cutting Concerns

> Concerns that affect 2+ services. Single source of truth here.

## Authentication
- Users authenticate via <OAuth provider> → gateway issues JWT
- Services trust each other via <mTLS / internal JWT / no-trust + per-call auth>
- See ADR: [transport-auth.md](docs/<PHASE-NN>/ADRs/...)

## Authorization
- Per-endpoint check in each service
- Roles: user, admin, partner-staff
- No centralized authz service in MVP (acceptable for size)

## Observability
- Logging: structured JSON, correlation ID propagated via header `X-Request-ID`
- Tracing: OpenTelemetry (planned, not in MVP)
- Metrics: Prometheus per-service `/metrics` (planned)
- Error reporting: <Sentry / similar>

## Schema evolution
- API versioning: URL path `/v1/...`, breaking changes → `/v2/...`
- Database migrations: Alembic per-service
- Event schemas: <if events used> registered in shared schema registry

## PII / Compliance
- No PII in logs (use IDs, hashes)
- See ADR: [pii-handling.md](docs/<PHASE-NN>/ADRs/...)
- Data retention: <policy>

## Deployment
- Docker compose for local
- <Production: k8s / fly.io / etc>
- One service = one container = independently deployable
```

### glossary.md

```markdown
# Glossary

> Domain terms used across architecture. Definitive source.

| Term | Definition | Where used |
|---|---|---|
| Bounded context | Domain area with own model/language. | architecture |
| Wellness score | Computed [-1, +1] metric of user health. | medical-service, ai-service |
| Connector | Adapter to external data source (wearable, calendar). | connector-service |
| ... | | |
```

## Process

1. **Read grilling artifact** from `brain-dumps/architecture/`
2. **Read existing `docs/current/architecture/`** if any — preserve what's still accurate
3. **Generate each file** with content grounded in grilling decisions:
   - Don't invent — only reflect what was decided
   - If something was discussed but not decided — mark `> TBD` and flag for next session
4. **Generate ADRs** for each cross-cutting decision visible in grilling:
   - One ADR per decision
   - Use `adr-format` skill template
5. **Generate diagrams** using `c4-diagrams` skill syntax:
   - Don't use generic flowcharts for L1/L2/L3
   - Use sequenceDiagram for data-flow files
6. **Cross-link** documents:
   - Every reference to another file is a markdown link
   - Glossary terms backlink to where they're defined
7. **Update AGENTS.md** if grilling produced "always true" rules:
   - Example: "LLM calls only through ai-service" → add to AGENTS.md if not there
8. **Suggest follow-up**:
   - Run `/architecture-review` to audit consistency
   - Create per-service PRDs via `/grill-me` if changes needed

## Don'ts

- ❌ Generate one big file — split into the structure above
- ❌ Invent decisions not made during grilling
- ❌ Skip "Failure modes" sections in data-flow files
- ❌ Use generic flowcharts where C4 syntax applies
- ❌ Inline service schemas — those belong in service repos
- ❌ Skip ADR generation — diagrams without ADRs rot
- ❌ Overwrite existing files without diff awareness — preserve current accurate content
