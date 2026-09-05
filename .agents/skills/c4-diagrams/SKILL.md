---
name: c4-diagrams
description: "Standard for drawing C4 architecture diagrams in Mermaid. Triggers when creating architecture documentation, drawing system/container/component diagrams, or discussing service topology. Enforces correct C4 Mermaid syntax over generic flowcharts."
---

# C4 Diagrams (Mermaid)

Architecture diagrams in this project follow the **C4 model**. Mermaid supports C4 natively — do NOT use generic `flowchart` syntax for architecture views.

## Four levels

| Level | Name | What's shown | Audience |
|---|---|---|---|
| 1 | System Context | Our system + external actors + external systems | Anyone |
| 2 | Container | Services, databases, queues, gateways | Developers, ops |
| 3 | Component | Inside one container | Developers of that service |
| 4 | Code | Class diagrams | Implementers (rarely useful) |

Don't draw L4 unless absolutely necessary. Don't mix levels in one diagram.

## L1 — System Context

Show our system as ONE box, with all external actors and systems around it. NO internal services visible.

```mermaid
C4Context
    title System Context — Alvion Health Platform

    Person(user, "End User", "Tracks health metrics, gets AI recommendations")
    Person_Ext(partnerClinic, "Partner Clinic Staff", "Provides lab services")

    System(alvion, "Alvion Platform", "Personal health data hub + AI insights")

    System_Ext(appleHealth, "Apple Health", "Wearable + iPhone health data")
    System_Ext(whoop, "Whoop", "Recovery and strain metrics")
    System_Ext(oura, "Oura Ring", "Sleep and readiness")
    System_Ext(google, "Google Calendar", "User calendar")
    System_Ext(openai, "OpenAI API", "LLM inference")
    System_Ext(stripe, "Stripe", "Payments")

    Rel(user, alvion, "Tracks metrics, asks questions", "HTTPS")
    Rel(partnerClinic, alvion, "Receives lab orders, sends results", "HTTPS")
    Rel(alvion, appleHealth, "Pulls metrics", "OAuth + HTTPS")
    Rel(alvion, whoop, "Pulls metrics", "OAuth + HTTPS")
    Rel(alvion, oura, "Pulls metrics", "OAuth + HTTPS")
    Rel(alvion, google, "Reads calendar", "OAuth")
    Rel(alvion, openai, "LLM completions", "HTTPS")
    Rel(alvion, stripe, "Charges users", "HTTPS")
```

## L2 — Container

Show services, databases, queues. NO classes, NO functions, NO internals of services.

```mermaid
C4Container
    title Container — Alvion Backend MVP

    Person(user, "User")

    System_Boundary(alvion, "Alvion Backend") {
        Container(gateway, "API Gateway", "FastAPI", "Routes + auth")
        Container(medical, "Medical Service", "Python/FastAPI", "User metrics + wellness score")
        Container(connector, "Connector Service", "Python/FastAPI", "Wearables ingest")
        Container(ai, "AI Service", "Python/FastAPI + LangChain", "LLM orchestration")
        Container(notification, "Notification Service", "Python/FastAPI", "Email/push")
        Container(geo, "Geo Service", "Python/FastAPI", "Location, clinic ranking")
        Container(payment, "Payment Service", "Python/FastAPI", "Stripe integration")

        ContainerDb(postgres, "PostgreSQL", "asyncpg", "User data, transactional")
        ContainerDb(redis, "Redis", "Cache", "Context cache, sessions")
        ContainerDb(qdrant, "Qdrant", "Vector store", "Medical knowledge embeddings")
    }

    System_Ext(wearables, "Wearables APIs", "Apple/Whoop/Oura")
    System_Ext(openai, "OpenAI")

    Rel(user, gateway, "API calls", "HTTPS")
    Rel(gateway, medical, "Forwards", "HTTP")
    Rel(gateway, ai, "Forwards", "HTTP")
    Rel(connector, wearables, "OAuth + pull", "HTTPS")
    Rel(connector, medical, "Ingest metrics", "HTTPX")
    Rel(ai, medical, "Read context", "HTTPX")
    Rel(ai, openai, "Completions", "HTTPS")
    Rel(ai, qdrant, "RAG retrieval", "gRPC")
    Rel(medical, postgres, "Read/write", "asyncpg")
    Rel(medical, redis, "Cache", "Redis protocol")
```

## L3 — Component

Show INSIDE one container. Only one service per diagram.

```mermaid
C4Component
    title Component — Medical Service

    Container_Ext(connector, "Connector Service")
    Container_Ext(ai, "AI Service")
    ContainerDb_Ext(postgres, "PostgreSQL")
    ContainerDb_Ext(redis, "Redis")

    Container_Boundary(medical, "Medical Service") {
        Component(ingestAPI, "Ingest API", "FastAPI router", "/internal/ingest endpoints")
        Component(queryAPI, "Query API", "FastAPI router", "/internal/context endpoints")
        Component(scorer, "Wellness Scorer", "Service layer", "Computes score [-1,+1]")
        Component(normalizer, "Source Normalizer", "Service layer", "Per-provider parsing")
        Component(repository, "Metric Repository", "Repository pattern", "DB access layer")
    }

    Rel(connector, ingestAPI, "POST /metrics/bulk", "HTTPX")
    Rel(ai, queryAPI, "GET /internal/context/{user_id}", "HTTPX")

    Rel(ingestAPI, normalizer, "")
    Rel(normalizer, repository, "")
    Rel(repository, postgres, "")

    Rel(queryAPI, scorer, "")
    Rel(queryAPI, repository, "")
    Rel(scorer, repository, "")
    Rel(queryAPI, redis, "Check cache")
```

## C4 element types

### People / Systems

```
Person(alias, "Label", "Description")              # internal user
Person_Ext(alias, "Label", "Description")          # external user

System(alias, "Label", "Description")              # our system (L1 only)
System_Ext(alias, "Label", "Description")          # external system

System_Boundary(alias, "Label") { ... }            # group of containers
```

### Containers (L2)

```
Container(alias, "Label", "Tech", "Description")
ContainerDb(alias, "Label", "Tech", "Description")     # for databases
ContainerQueue(alias, "Label", "Tech", "Description")  # for queues

Container_Ext(...)     # external container (when viewing one service)
ContainerDb_Ext(...)
```

### Components (L3)

```
Component(alias, "Label", "Tech", "Description")
ComponentDb(alias, "Label", "Tech", "Description")
```

### Relationships

```
Rel(from, to, "Label", "Tech")          # solid arrow
Rel_Back(from, to, "Label")             # backwards relationship
BiRel(a, b, "Label", "Tech")            # bidirectional
```

Arrow position can be controlled with directional variants:
```
Rel_Up(from, to, "...")
Rel_Down(from, to, "...")
Rel_Left(from, to, "...")
Rel_Right(from, to, "...")
```

## Sequence diagrams (for data-flow/)

For request flows, use Mermaid `sequenceDiagram` (not C4):

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Gateway
    participant Medical as Medical Service
    participant Postgres
    participant Redis

    User->>Gateway: GET /me/context
    Gateway->>Medical: forward request
    Medical->>Redis: GET ctx:{user_id}
    alt Cache hit
        Redis-->>Medical: cached context
    else Cache miss
        Medical->>Postgres: SELECT user metrics
        Postgres-->>Medical: rows
        Medical->>Redis: SET ctx:{user_id} TTL 5min
    end
    Medical-->>Gateway: context JSON
    Gateway-->>User: 200 OK + context
```

## Forbidden patterns

- ❌ Generic `flowchart TD` for architecture (use C4 syntax)
- ❌ Mixing levels: `Container` and `Component` in same diagram
- ❌ Showing database internals at L2 (that's L3+)
- ❌ Boxes with technology names only ("PostgreSQL") without capability ("User data store")
- ❌ Arrows without labels (you must label what flows)
- ❌ More than ~15 elements in a single diagram (split it)
- ❌ Bidirectional arrows where direction matters (use two `Rel`)

## When to use which type

| Need | Diagram type |
|---|---|
| Show external integrations | `C4Context` |
| Show all our services | `C4Container` |
| Show inside one service | `C4Component` |
| Show a request flow over time | `sequenceDiagram` |
| Show entity relationships | `erDiagram` |
| Show state transitions | `stateDiagram-v2` |
| Show deployment topology | `C4Deployment` (advanced) |
| Show generic process flow (non-arch) | `flowchart` |

## Naming conventions

- Service aliases: lowercase, no hyphens (`medical` not `medical-service` in alias; but label is `"Medical Service"`)
- Labels in quotes use proper noun casing: `"Medical Service"`, not `"medical service"`
- Tech tag is short and concrete: `"FastAPI"`, `"asyncpg"`, `"Redis 7"`
- Description tag is one sentence about capability
