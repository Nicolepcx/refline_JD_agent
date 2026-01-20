# Application Architecture Diagrams

This document provides visual representations of the Job Description Writer application architecture using Mermaid diagrams.

## Table of Contents

1. [System Overview](#system-overview)
2. [Component Architecture](#component-architecture)
3. [Data Flow Diagram](#data-flow-diagram)
4. [Blackboard Architecture Workflow](#blackboard-architecture-workflow)
5. [Database & Memory Architecture](#database--memory-architecture)
6. [Generation Pipeline](#generation-pipeline)
7. [UI Component Structure](#ui-component-structure)

---

## System Overview


```mermaid
graph TB
    subgraph "User Interface Layer"
        UI[Streamlit UI]
        Editor[Content Editor]
        Preview[Live Preview]
        Sidebar[Configuration Sidebar]
        ScraperPanel[Company Scraping Panel]
    end
    
    subgraph "Application Layer"
        App[app.py<br/>Main Entry Point]
        Agent[agent.py<br/>Intent Routing]
        Services[services/<br/>Service Layer]
    end
    
    subgraph "Business Logic Layer"
        Generator[generators/<br/>Job Generator]
        Ruler[ruler/<br/>RULER Ranking]
        Graph[graph/<br/>Blackboard Workflow]
    end
    
    subgraph "Data Layer"
        Models[models/<br/>Pydantic Models]
        DB[(ORM Database<br/>SQLAlchemy)]
        Store[LangGraph Store<br/>InMemoryStore]
        Checkpoint[LangGraph Checkpointer<br/>AsyncSqliteSaver]
        VectorDB[(Vector Database<br/>FAISS/Chroma)]
    end
    
    subgraph "External Services"
        LLM[LLM Services<br/>Nebius API]
        OpenAI[OpenAI API<br/>RULER Judge]
    end
    
    UI --> App
    Editor --> App
    Preview --> App
    Sidebar --> App
    ScraperPanel --> App
    
    App --> Services
    Agent --> Services
    
    Services --> Generator
    Services --> Ruler
    Services --> Graph
    
    Generator --> Models
    Ruler --> Models
    Graph --> Models
    
    Generator --> LLM
    Ruler --> OpenAI
    Graph --> LLM
    
    Services --> DB
    Graph --> Store
    Graph --> Checkpoint
    Graph --> VectorDB
    
    DB -.Sync.-> Store
    ScraperPanel --> VectorDB
```

---

## Component Architecture

```mermaid
graph LR
    subgraph "UI Components"
        A[app.py]
        B[ui/layout.py]
        C[ui/config_panel.py]
        D[ui/feedback_panel.py]
        E[ui/components.py]
    end
    
    subgraph "Core Services"
        F[agent.py]
        G[services/job_service.py]
        H[services/graph_service.py]
    end
    
    subgraph "Generation Logic"
        I[generators/job_generator.py]
        J[ruler/ruler_utils.py]
        K[graph/job_graph.py]
    end
    
    subgraph "Data Models"
        L[models/job_models.py]
        M[helpers/config_helper.py]
        N[utils.py]
    end
    
    subgraph "Infrastructure"
        O[llm_service.py]
        P[database/models.py]
        Q[database/store_sync.py]
        R[config.py]
    end
    
    A --> B
    A --> C
    A --> D
    A --> E
    A --> F
    
    B --> G
    C --> G
    D --> G
    F --> G
    
    G --> H
    G --> I
    G --> J
    
    H --> K
    I --> L
    J --> L
    K --> L
    
    G --> M
    M --> L
    G --> N
    N --> L
    
    I --> O
    J --> O
    K --> O
    
    G --> P
    H --> Q
    Q --> P
    
    O --> R
    P --> R
```

---

## Data Flow Diagram

```mermaid
sequenceDiagram
    participant User
    participant UI as Streamlit UI
    participant App as app.py
    participant Service as job_service.py
    participant Graph as graph_service.py
    participant Blackboard as Blackboard Graph
    participant DB as ORM Database
    participant Store as LangGraph Store
    participant LLM as LLM API
    
    User->>UI: Enter job title & config
    UI->>App: User input
    App->>Service: generate_full_job_description()
    
    Service->>Graph: generate_job_with_blackboard()
    Graph->>DB: Get gold standards & feedback
    DB-->>Graph: Return data
    Graph->>Store: Sync data to store
    Store-->>Graph: Confirmed
    
    Graph->>Blackboard: Execute workflow
    Blackboard->>Store: Read gold standards
    Store-->>Blackboard: Gold standards
    Blackboard->>LLM: Generate candidates
    LLM-->>Blackboard: Job candidates
    
    Blackboard->>Store: Read user gripes
    Store-->>Blackboard: User gripes
    Blackboard->>LLM: Refine candidates
    LLM-->>Blackboard: Refined candidates
    
    Blackboard->>LLM: RULER ranking
    LLM-->>Blackboard: Ranked candidates
    Blackboard-->>Graph: Best candidate
    
    Graph-->>Service: Job body dict
    Service-->>App: Result
    App->>UI: Update session state
    UI-->>User: Display job description
    
    User->>UI: Accept/Reject/Edit
    UI->>DB: Save feedback
    DB->>Store: Sync to store (async)
```

---

## Blackboard Architecture Workflow

```mermaid
graph TD
    Start([START]) --> Scrape[Scrape Company<br/>node_scrape_company<br/>Optional, Modular]
    Scrape --> Generator[Generator Expert<br/>node_generator_expert]
    
    Generator --> |Read| GoldStandards[(Gold Standards<br/>from Store)]
    GoldStandards --> |Few-Shot Examples| Generator
    Generator --> |Generate| Candidates[Blackboard<br/>Candidates List]
    
    Candidates --> RulerScorer[RULER Scorer<br/>node_ruler_scorer<br/>Test-Time Compute]
    RulerScorer --> |Score| Judge[LLM Judge<br/>RULER Scoring]
    Judge --> |Scores| RulerScorer
    RulerScorer --> |Store Scores| Candidates
    
    Candidates --> Conditional{Need Refinement?<br/>HITL or Low Scores}
    
    Conditional -->|Yes| Style[Style Expert<br/>node_style_expert]
    Conditional -->|No| Curator[RULER Curator<br/>node_ruler_curator]
    
    Style --> |Read| Gripes[(User Gripes<br/>from Store)]
    Gripes --> |HITL Feedback| Style
    Style --> |Read| RulerScores[(RULER Scores<br/>from State)]
    RulerScores --> |Quality Issues| Style
    Style --> |Refine| Candidates
    
    Candidates --> Curator
    Curator --> |Select Best| Winner[Best Candidate]
    
    Winner --> Persist[Persist Feedback<br/>node_persist_feedback_to_store]
    Persist --> |Save| Store[(LangGraph Store)]
    Persist --> |Save| DB[(ORM Database)]
    
    Store --> |Next Run| Generator
    DB --> |UI Display| History[History Panel]
    
    Persist --> End([END])
    
    style Generator fill:#e1f5ff
    style Style fill:#fff4e1
    style RulerScorer fill:#ffe1f5
    style Curator fill:#ffe1f5
    style Candidates fill:#f0f0f0
    style GoldStandards fill:#d4edda
    style Gripes fill:#f8d7da
    style Conditional fill:#fff3cd
```

---

## Database & Memory Architecture

```mermaid
graph TB
    subgraph UA["User Actions"]
        Accept["User Accepts JD"]
        Reject["User Rejects JD"]
        Edit["User Edits JD"]
    end

    subgraph DB["ORM Database (SQLAlchemy)"]
        GS["GoldStandard<br/>job_title<br/>job_body_json<br/>config_json"]
        UF["UserFeedback<br/>feedback_type<br/>feedback_text<br/>job_body_json"]
        INT["Interaction<br/>interaction_type<br/>input_data<br/>output_data<br/>metadata"]
    end

    subgraph Store["LangGraph Store (InMemoryStore)"]
        GS_Store["(user_id, gold_standard)<br/><b>Key</b>: job_title<br/><b>Value</b>: body + config"]
        Gripes_Store["(user_id, user_gripes)<br/><b>Key</b>: unique_id<br/><b>Value</b>: feedback + type"]
    end

    subgraph CP["LangGraph Checkpointer"]
        Threads["jd_threads.sqlite<br/>Thread State<br/>JobState<br/>Messages<br/>Candidates"]
    end

    subgraph BB["Blackboard Experts"]
        GenExp["Generator Expert<br/>Reads Gold Standards"]
        StyleExp["Style Expert<br/>Reads User Gripes"]
    end

    Accept --> GS
    Reject --> UF
    Edit --> UF
    Accept --> INT
    Reject --> INT
    Edit --> INT

    GS -.sync_all_to_store.-> GS_Store
    UF -.sync_all_to_store.-> Gripes_Store

    GS_Store --> GenExp
    Gripes_Store --> StyleExp

    GenExp --> Threads
    StyleExp --> Threads

    style GS fill:#d4edda
    style UF fill:#f8d7da
    style INT fill:#d1ecf1
    style GS_Store fill:#fff3cd
    style Gripes_Store fill:#fff3cd
    style Threads fill:#e2e3e5

```

---

## Generation Pipeline

```mermaid
flowchart TD
    Start([User Clicks<br/>Generate Full JD]) --> Check{Use RULER?}
    
    Check -->|Yes| Blackboard[Blackboard Architecture]
    Check -->|No| Blackboard
    
    Blackboard --> Config[Load JobGenerationConfig<br/>from Session State]
    Config --> Sync[Sync ORM DB → LangGraph Store]
    
    Sync --> Graph[Build LangGraph Workflow]
    Graph --> Init[Initialize JobState]
    
    Init --> Scrape[Scrape Company Info<br/>Optional, Modular]
    Scrape --> Gen[Generator Expert]
    
    Gen --> |Read| Gold[Gold Standards<br/>from Store]
    Gold --> |Few-Shot Examples| Gen
    Gen --> |Generate| Cand1[3 Candidates<br/>with temp jitter]
    
    Cand1 --> RulerScorer[RULER Scorer<br/>Test-Time Compute]
    RulerScorer --> |Score| Judge1[LLM Judge<br/>openai/o3-mini]
    Judge1 --> |Scores| RulerScorer
    RulerScorer --> |Store Scores| Cand1
    
    Cand1 --> RefineCheck{Need Refinement?<br/>HITL or Low Scores}
    
    RefineCheck -->|Yes| Style[Style Expert]
    RefineCheck -->|No| Curator[RULER Curator]
    
    Style --> |Read| Gripes[User Gripes<br/>from Store]
    Gripes --> |HITL Feedback| Style
    Style --> |Read| Scores[RULER Scores]
    Scores --> |Quality Issues| Style
    Style --> |Refine| Cand2[Refined Candidates]
    
    Cand2 --> Curator
    Curator --> |Use/Re-score| Judge2[LLM Judge<br/>if needed]
    Judge2 --> |Rank| Ranked[Ranked Candidates]
    Ranked --> |Best| Select[Select Best Candidate]
    
    Select --> Parse[Parse JobBody JSON]
    Parse --> Convert[Convert to Dict]
    Convert --> StoreRankings[Store RULER Rankings<br/>in Session State]
    StoreRankings --> Update[Update Session State]
    Update --> Display[Display in UI]
    
    Display --> End([END])
    
    style Blackboard fill:#e1f5ff
    style RulerScorer fill:#ffe1f5
    style Curator fill:#ffe1f5
    style Gen fill:#fff4e1
    style Style fill:#fff4e1
    style Gold fill:#d4edda
    style Gripes fill:#f8d7da
    style RefineCheck fill:#fff3cd
```

---

## UI Component Structure

```mermaid
graph TD
    subgraph "app.py - Main Entry"
        Main[app.py]
        Init[Initialize Session State]
        Render[Render UI Components]
    end
    
    subgraph "UI Layout (ui/layout.py)"
        Header[render_header<br/>Top Navigation Bar]
        Title[render_title<br/>Dynamic Page Title]
        Nav[render_navigation<br/>Tab Navigation]
        Editor[render_content_editor<br/>Left Column Form]
        Preview[render_preview<br/>Right Column Preview]
        ScraperPanel[Company Scraping Panel<br/>Sidebar]
    end
    
    subgraph "Configuration Panel (ui/config_panel.py)"
        ConfigSidebar[render_config_sidebar<br/>Generation Settings]
        RulerRankings[render_ruler_rankings<br/>RULER Rankings Display]
        TempDisplay[Temperature Breakdown]
    end
    
    subgraph "Feedback Panel (ui/feedback_panel.py)"
        Feedback[render_feedback_buttons<br/>Accept/Reject/Edit]
        History[render_history_panel<br/>Gold Standards/Feedback/History]
    end
    
    subgraph "Components (ui/components.py)"
        AIField[ai_field<br/>Text Area Component]
    end
    
    Main --> Init
    Main --> Render
    
    Render --> Header
    Render --> Title
    Render --> Nav
    Render --> Editor
    Render --> Preview
    Render --> ScraperPanel
    
    Main --> ConfigSidebar
    ConfigSidebar --> RulerRankings
    ConfigSidebar --> TempDisplay
    
    Main --> Feedback
    Main --> History
    
    Editor --> AIField
    
    style Main fill:#e1f5ff
    style Editor fill:#fff4e1
    style Preview fill:#d4edda
    style ConfigSidebar fill:#ffe1f5
    style Feedback fill:#f8d7da
```

---

## Service Layer Architecture

```mermaid
graph LR
    subgraph "Entry Points"
        UI[Streamlit UI]
        Agent[Chat Agent]
    end
    
    subgraph "Service Layer (services/)"
        JobService[job_service.py<br/>generate_full_job_description<br/>generate_job_section]
        GraphService[graph_service.py<br/>generate_job_with_blackboard<br/>generate_with_graph]
    end
    
    subgraph "Generation Methods"
        Simple[Simple LLM<br/>call_llm]
        Advanced[Advanced Generator<br/>render_job_body]
        Blackboard[Blackboard Graph<br/>LangGraph Workflow]
        Ruler[RULER Ranking<br/>generate_best_job_body_with_ruler]
    end
    
    subgraph "Data Models"
        Config[JobGenerationConfig]
        JobBody[JobBody]
    end
    
    UI --> JobService
    Agent --> JobService
    
    JobService --> Simple
    JobService --> Advanced
    JobService --> Blackboard
    JobService --> Ruler
    
    Blackboard --> GraphService
    GraphService --> Blackboard
    
    Advanced --> Config
    Blackboard --> Config
    Ruler --> Config
    
    Advanced --> JobBody
    Blackboard --> JobBody
    Ruler --> JobBody
    
    Simple --> LLM1[Base LLM]
    Advanced --> LLM1
    Blackboard --> LLM1
    Ruler --> LLM2[Judge LLM]
    
    style JobService fill:#e1f5ff
    style GraphService fill:#fff4e1
    style Blackboard fill:#ffe1f5
    style Ruler fill:#d4edda
```

---

## RULER Ranking Flow

```mermaid
sequenceDiagram
    participant User
    participant Service as job_service.py
    participant Ruler as ruler_utils.py
    participant Traj as Trajectory Conversion
    participant Judge as RULER Judge LLM
    participant UI as Sidebar Display
    
    User->>Service: Generate with RULER enabled
    Service->>Ruler: generate_best_job_body_with_ruler()
    
    loop For each candidate
        Ruler->>Generator: generate_job_body_candidate()
        Generator-->>Ruler: JobBody candidate
    end
    
    Ruler->>Traj: jd_candidate_to_trajectory()
    Traj-->>Ruler: Trajectory objects
    
    Ruler->>Judge: ruler_score_group(trajectories)
    Judge->>Judge: Evaluate quality
    Judge-->>Ruler: Scored trajectories
    
    Ruler->>Ruler: Sort by score (descending)
    Ruler-->>Service: (best_job_body, scored_candidates)
    
    Service->>Service: Extract rankings
    Service->>UI: Store in session_state
    UI-->>User: Display rankings in sidebar
    
    Note over UI: Shows:<br/>- Best score metric<br/>- All rankings with scores<br/>- Job description previews
```

---

## Configuration Flow

```mermaid
graph TD
    Start([User Changes Settings]) --> Sidebar[Sidebar UI Components]
    
    Sidebar --> Language[Language Selector]
    Sidebar --> Formality[Formality Selector]
    Sidebar --> Company[Company Type Selector]
    Sidebar --> Industry[Industry Selector]
    Sidebar --> Seniority[Seniority Selector]
    Sidebar --> Skills[Skills Text Area]
    Sidebar --> Benefits[Benefit Keywords]
    Sidebar --> Ruler[Use RULER Checkbox]
    Sidebar --> NumCand[Number of Candidates Slider]
    
    Language --> Session[Session State]
    Formality --> Session
    Company --> Session
    Industry --> Session
    Seniority --> Session
    Skills --> Session
    Benefits --> Session
    Ruler --> Session
    NumCand --> Session
    
    Session --> Helper[config_helper.py<br/>get_job_config_from_session]
    
    Helper --> ParseSkills[_parse_skills_from_session]
    Helper --> ParseBenefits[_parse_benefits_from_session]
    
    ParseSkills --> Config[JobGenerationConfig]
    ParseBenefits --> Config
    
    Config --> Temp[Calculate Temperature<br/>Based on settings]
    Temp --> Config
    
    Config --> Generate[Generation Process]
    
    style Session fill:#e1f5ff
    style Config fill:#fff4e1
    style Temp fill:#ffe1f5
```

---

## Notes

- All diagrams use Mermaid syntax and can be rendered in:
  - GitHub/GitLab markdown viewers
  - VS Code with Mermaid extension
  - Online Mermaid editors (mermaid.live)
  - Documentation platforms (MkDocs, Sphinx with extensions)

- Colors in diagrams:
  - Blue: UI/Entry points
  - Yellow: Generation/Processing
  - Pink: RULER/Quality evaluation
  - Green: Data storage
  - Red: Feedback/Errors

- For interactive viewing, copy the Mermaid code blocks to [mermaid.live](https://mermaid.live) or use a Mermaid-compatible viewer.

