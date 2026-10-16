# NW Digital Operations Hub V3 - Architecture & Database ERD

This document contains the visual system architecture and the Entity Relationship Diagram (ERD) for the **NW Digital Operations Hub V3**. 

*(Note: If you are viewing this file on GitHub or in a Markdown viewer that supports Mermaid, the diagrams below will render visually. Otherwise, you can copy the code blocks below and paste them into [Mermaid Live Editor](https://mermaid.live/) to view or export them as PNG/PDF).*

---

## 1. System Architecture Diagram

This diagram shows how users connect via HTTPS/WebSockets through the API Gateway, and how requests are routed to the core services and sub-services:

```mermaid
graph TD
    User([User / Client / Admin]) -->|HTTPS / WSS| Gateway[API Gateway - FastAPI]
    
    subgraph Core Platform [Core Platform Services]
        Gateway --> Auth[Auth & User Management]
        Gateway --> TenantMiddleware[Tenant & Role Middleware]
        Gateway --> Messaging[Messaging & Client Rooms WebSockets]
        Gateway --> Marketing[Marketing & Approvals Engine]
        Gateway --> Scheduler[Task Scheduler & Queue]
    end

    subgraph Internal Sub-Services [Intern Modules]
        Gateway -->|Proxy Service Request| VishaqaAPI[Vishaqa AI/Marketing API]
        Gateway -->|Proxy Service Request| AsmaAPI[Asma Service API]
        Gateway -->|Proxy Service Request| EshaAPI[Esha Service API]
    end

    subgraph Data & Storage [Shared Infrastructure]
        Auth --> DB[(PostgreSQL Shared DB)]
        TenantMiddleware --> DB
        Messaging --> DB
        Marketing --> DB
        Scheduler --> RedisQueue[(Redis / Celery Queue)]
        Scheduler --> DB
        Marketing --> S3[(Secure Object Storage - AWS S3 / MinIO)]
    end
    
    classDef primary fill:#4A90E2,stroke:#1A5276,stroke-width:2px,color:#fff;
    classDef secondary fill:#2ECC71,stroke:#27AE60,stroke-width:2px,color:#fff;
    classDef storage fill:#F1C40F,stroke:#D4AC0D,stroke-width:2px,color:#333;
    class Gateway,Auth,TenantMiddleware,Messaging,Marketing,Scheduler primary;
    class VishaqaAPI,AsmaAPI,EshaAPI secondary;
    class DB,RedisQueue,S3 storage;
```

### Key Architectural Layers:
1. **API Gateway (FastAPI)**: Handled on port `8000`, routes traffic, processes JWT authentication, resolves `tenant_id` from the request token, and proxies requests to individual intern services.
2. **Core Services**: Handles protected WebSocket communication (messenger/client rooms), approval state machines, and task queues.
3. **Intern Services**: Independent FastAPI services built by Vishaqa, Asma, and Esha, connected via HTTP routing through the gateway.
4. **Shared Database**: PostgreSQL with Alembic migrations, with strict tenant isolation filter rules.

---

## 2. Database ERD (Entity Relationship Diagram)

Here is a visual representation of the Entity Relationship Diagram:

![Database ERD Diagram](./database_erd_diagram.png)

This schema outlines the relationships, primary/foreign keys, and data scopes for all platform entities:

```mermaid
erDiagram
    TENANTS {
        uuid id PK
        string name
        string status
        timestamp created_at
    }
    USERS {
        uuid id PK
        uuid tenant_id FK
        string email
        string password_hash
        string full_name
        string role "super_admin | tenant_admin | designer | client_rep"
        boolean is_active
        string phone_number
        timestamp created_at
    }
    CLIENTS {
        uuid id PK
        uuid tenant_id FK
        string company_name
        string industry
        string contact_email
        timestamp created_at
    }
    CLIENT_ROOMS {
        uuid id PK
        uuid client_id FK
        uuid tenant_id FK
        string status
        timestamp created_at
    }
    MESSAGES {
        uuid id PK
        uuid client_room_id FK
        uuid conversation_id
        uuid sender_id FK
        string content_type "text | file | system"
        text content
        string visibility "external | internal"
        timestamp created_at
    }
    CAMPAIGNS {
        uuid id PK
        uuid client_id FK
        uuid tenant_id FK
        string name
        string status "draft | pending_approval | approved | scheduled | published"
        timestamp scheduled_publish_at
        timestamp created_at
    }
    CONTENT_VERSIONS {
        uuid id PK
        uuid campaign_id FK
        string version_number
        text ai_output
        text edited_content
        string status "pending | approved | rejected"
        uuid approved_by FK
        timestamp created_at
    }
    PUBLISHING_JOBS {
        uuid id PK
        uuid campaign_id FK
        string status "queued | processing | completed | failed | manual_handoff"
        string idempotency_key
        int retry_count
        text error_logs
        timestamp scheduled_at
    }
    AUDIT_EVENTS {
        uuid id PK
        uuid tenant_id FK
        uuid user_id FK
        string action_name
        string entity_name
        uuid entity_id
        text diff_data
        string ip_address
        timestamp created_at
    }

    TENANTS ||--o{ USERS : owns
    TENANTS ||--o{ CLIENTS : owns
    TENANTS ||--o{ CLIENT_ROOMS : owns
    TENANTS ||--o{ CAMPAIGNS : owns
    TENANTS ||--o{ AUDIT_EVENTS : logs
    
    CLIENTS ||--o{ CLIENT_ROOMS : contains
    CLIENTS ||--o{ CAMPAIGNS : targets
    
    USERS ||--o{ MESSAGES : sends
    USERS ||--o{ AUDIT_EVENTS : triggers
    
    CAMPAIGNS ||--o{ CONTENT_VERSIONS : tracks
    CAMPAIGNS ||--o{ PUBLISHING_JOBS : triggers
```

### Table Definitions & Ownership rules:
*   **Tenants & Security**: Users and Clients are strictly linked to a specific `Tenant`. No cross-tenant SQL joins are permitted.
*   **Client Rooms split**: Message visibility is categorized as `external` (clients can see it) or `internal` (only designers/admins can see it).
*   **Audit Logging**: The `AUDIT_EVENTS` table registers all actions on database entities for compliance.
