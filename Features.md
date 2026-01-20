# Features & Configuration Guide

This document describes all features, settings, and how to activate/deactivate components in the Job Description Writer application.

## Table of Contents

1. [Generation Modes](#generation-modes)
2. [Configuration Settings](#configuration-settings)
3. [Blackboard Architecture](#blackboard-architecture)
4. [RULER Quality Evaluation](#ruler-quality-evaluation)
5. [Database & Memory](#database--memory)
6. [User Feedback System](#user-feedback-system)
7. [UI Components](#ui-components)
8. [Activation/Deactivation Guide](#activationdeactivation-guide)

---

## Generation Modes

The application supports three generation modes:

### 1. Simple Generation
- **Status**: Always available
- **Description**: Basic LLM-based generation using simple prompts
- **Use Case**: Quick, straightforward job description generation
- **Activation**: Disable "Use Advanced Generation" in sidebar

### 2. Advanced Generation
- **Status**: Default enabled
- **Description**: Structured generation using `JobGenerationConfig` with configurable parameters
- **Features**:
  - Language selection (English/German)
  - Tone/formality control
  - Industry-specific defaults
  - Seniority-based adjustments
  - Skill and benefit customization
- **Activation**: Check "Use Advanced Generation" in sidebar (default: ON)

### 3. Blackboard Architecture
- **Status**: Always enabled when Advanced Generation is on
- **Description**: Multi-expert workflow with memory and learning capabilities
- **Features**:
  - Generator Expert: Creates initial candidates using gold standards
  - Style Expert: Refines based on user feedback
  - RULER Curator: Ranks and selects best candidate
  - Persistent memory across sessions
- **Activation**: Automatic when "Use Advanced Generation" is enabled
- **Note**: Learns from past interactions and improves over time

---

## Configuration Settings

All settings are available in the sidebar under "⚙️ Generation Settings".

### Basic Settings

#### Use Advanced Generation
- **Location**: Sidebar → Generation Settings
- **Type**: Checkbox
- **Default**: Enabled
- **Effect**: Enables structured generation with configurable parameters
- **When to use**: For better control over output style and content

#### Blackboard Architecture
- **Status**: Always enabled with Advanced Generation
- **Effect**: Uses multi-expert workflow with memory
- **Note**: The system automatically learns from past interactions when Advanced Generation is enabled

### Advanced Generation Parameters

#### Language
- **Options**: `en` (English), `de` (German)
- **Default**: `en`
- **Effect**: Determines the language of generated content
- **Location**: Sidebar → Generation Settings

#### Tone / Formality
- **Options**: `casual`, `neutral`, `formal`
- **Default**: `neutral`
- **Effect**: Controls the tone of the job description
  - **Casual**: Friendly, modern, but professional
  - **Neutral**: Clear, professional
  - **Formal**: Corporate, conservative
- **Impact on Temperature**: Affects LLM temperature (casual = higher, formal = lower)

#### Company Type
- **Options**: `startup`, `scaleup`, `corporate`, `public_sector`, `agency`, `consulting`
- **Default**: `scaleup`
- **Effect**: Influences tone and content style
- **Impact on Temperature**: Startup (+0.05), Public Sector (-0.05)

#### Industry
- **Options**: `generic`, `finance`, `healthcare`, `public_it`, `ai_startup`, `ecommerce`, `manufacturing`
- **Default**: `generic`
- **Effect**: 
  - Sets industry-specific benefit defaults
  - Adjusts temperature
  - Influences content style
- **Auto-adjustments**:
  - `public_it` → sets company_type to `public_sector`
  - `ai_startup` → sets company_type to `startup`

#### Seniority Level
- **Options**: Not specified, `intern`, `junior`, `mid`, `senior`, `lead`, `principal`
- **Default**: Not specified
- **Effect**: Adjusts requirements and tone
- **Impact on Temperature**: Senior roles (-0.05), Junior/Intern (+0.05)

#### Experience Years
- **Min Years Experience**: 0-20 (0 = not specified)
- **Max Years Experience**: 0-20 (0 = not specified)
- **Effect**: Included in generation prompt for appropriate requirements

#### Required Skills
- **Type**: Multi-line text area
- **Format**: One skill per line
- **Optional Format**: `Skill Name (category, level)`
  - Example: `Python (backend, advanced)`
  - Example: `React (frontend, intermediate)`
- **Effect**: Skills are incorporated into requirements section

#### Benefit Keywords
- **Type**: Multi-line text area
- **Format**: 
  - Comma-separated: `"hybrid work in Switzerland, continuing education in AI and ML"`
  - Newline-separated: One keyword per line
  - Mixed: Can combine both formats across multiple lines
- **Effect**: **STRICT RESTRICTION** - Only these exact keywords will be used in the benefits section
- **Behavior**: 
  - If keywords provided: Creates exactly one benefit per keyword, no additional benefits added
  - If no keywords provided: Benefits section will be empty
- **Post-processing**: System filters generated benefits to ensure only provided keywords are included
- **Auto-population**: Industry-specific defaults when industry is selected (can be overridden)

### RULER Settings

#### Use RULER Ranking
- **Location**: Sidebar → Generation Settings (only visible when Advanced Generation is enabled)
- **Type**: Checkbox
- **Default**: Disabled
- **Effect**: Generates multiple candidates and uses RULER to rank them
- **When to use**: For highest quality output (slower generation)

#### Number of Candidates
- **Location**: Sidebar → Generation Settings (only visible when RULER is enabled)
- **Type**: Slider (2-5)
- **Default**: 3
- **Effect**: More candidates = better quality but slower generation
- **Recommendation**: 3 for balance, 5 for maximum quality

---

## Blackboard Architecture

### Overview

The blackboard architecture uses a multi-expert workflow where different "experts" collaborate through a shared blackboard (candidates list).

### Expert Nodes

1. **Scrape Company** ✅ **IMPLEMENTED**
   - **Function**: Scrapes company information from URLs and stores in vector database
   - **Storage**: FAISS vector store (local) or Chroma (optional)
   - **Features**:
     - Scrapes up to 3 company URLs
     - Stores content by company name
     - Configurable scraping intervals (daily, weekly, monthly, etc.)
     - Retrieves existing content from vector store before scraping
     - Modular: Blackboard architecture works without scraping enabled
   - **Usage**: Configure URLs in sidebar → Company Scraping panel

2. **Generator Expert** ✅ **ENHANCED**
   - **Function**: Creates initial job description candidates using gold standards as few-shot examples
   - **Memory**: Uses gold standards from store (with smart matching by job title and config)
   - **Gold Standards Usage**: 
     - Retrieves gold standards matching job title and config (company type, industry, formality)
     - Uses them as few-shot examples in prompt (up to 2 examples)
     - Falls back gracefully if no gold standards exist
     - Maintains company identity while adapting to job-specific requirements
   - **Output**: Adds 3 candidates to blackboard
   - **Temperature Jitter**: Varies temperature slightly for diversity
   - **Context Engineering**: Structured prompt with conditional examples section

3. **RULER Scorer** 🆕 **NEW NODE**
   - **Function**: Scores all candidates using RULER (test-time compute)
   - **Purpose**: Provides quality scores before refinement
   - **Output**: Stores RULER scores in state (candidate index → score)
   - **Usage**: Scores guide Style Expert refinement decisions

4. **Style Expert** ✅ **ENHANCED**
   - **Function**: Refines candidates based on HITL feedback and RULER scores
   - **Refinement Triggers**:
     - **HITL (Human-in-the-Loop)**: User feedback from UI (primary source)
     - **RULER-based**: Candidates scoring below threshold (0.7) need improvement
   - **Memory**: Uses user gripes (rejections/edits) from store
   - **Smart Matching**: Prioritizes job-specific feedback over general feedback
   - **Company Context**: Uses scraped company content for style consistency
   - **Output**: Refined candidates (only if feedback exists or RULER indicates need)
   - **Modular**: Skips refinement if no feedback and all scores are good

5. **RULER Curator** ✅ **ENHANCED**
   - **Function**: Selects best candidate from blackboard
   - **Method**: Uses existing RULER scores if available, otherwise re-scores
   - **Output**: Best candidate based on score
   - **Fallback**: Uses first candidate if RULER fails

5. **Persist**
   - **Function**: Saves results to database
   - **Actions**:
     - Accepted jobs → Gold standards
     - Rejections/Edits → User gripes
   - **Side-effect**: No state change, only persistence

### Workflow (Less Sequential, Conditional Refinement)

```
START → Scrape Company (optional, modular)
    ↓
Generator Expert (uses gold standards as few-shot examples)
    ↓
RULER Scorer (test-time compute - scores all candidates)
    ↓
[Conditional] → Style Expert (if HITL feedback OR low RULER scores)
    OR
    ↓
RULER Curator (selects best using existing scores)
    ↓
Persist → END
```

### Memory Usage

- **Gold Standards**: 
  - Retrieved by Generator Expert using job title similarity and config matching
  - Used as few-shot examples in generation prompt
  - Smart matching: prioritizes job-specific examples, then general company style
  - Falls back gracefully if no gold standards exist
- **User Gripes**: 
  - Retrieved by Style Expert for HITL-based refinement
  - Prioritizes job-specific feedback over general feedback
- **Storage**: 
  - ORM Database: `jd_database.sqlite` (for UI/history)
  - LangGraph Store: InMemoryStore (for blackboard experts)
  - Vector DB: `vector_store/` (for company scraped content)

---

## RULER Quality Evaluation

### What is RULER?

RULER (Reward Understanding for Language Model Evaluation and Ranking) is an automatic quality evaluation system that scores job description candidates.

### How It Works

1. **Candidate Generation**: Creates multiple candidates with temperature jitter
2. **Trajectory Conversion**: Converts each candidate to a trajectory format
3. **Scoring**: Uses a judge model to evaluate quality
4. **Ranking**: Sorts candidates by score
5. **Selection**: Returns the highest-scoring candidate

### Judge Model

- **Default**: `openai/o3-mini`
- **Evaluation Criteria**:
  - Clarity
  - Tone alignment
  - Role alignment
  - Usefulness to candidates
  - Seniority level match
  - Company type/industry realism

### Activation

1. Enable "Use Advanced Generation"
2. Enable "Use RULER Ranking"
3. Set number of candidates (2-5)
4. Generate job description

### Performance

- **Speed**: Slower than single generation (generates N candidates + scoring)
- **Quality**: Higher quality output (best of N candidates)
- **Cost**: Higher API costs (N generations + judge calls)

---

## Database & Memory

### Architecture Overview

The application uses a **dual-database architecture**:

1. **ORM Database (SQLAlchemy)**: Django-style ORM for structured data
   - Gold standards, user feedback, interactions
   - Used for UI display and analytics
   - File: `jd_database.sqlite`

2. **LangGraph Store (InMemoryStore/Persistent)**: LangGraph's store system
   - User memories across threads
   - Namespace-based: `(user_id, "gold_standard")` and `(user_id, "user_gripes")`
   - Used by blackboard architecture experts
   - Automatically synced from ORM database

3. **LangGraph Checkpointer (SQLite)**: Thread state management
   - Conversation thread storage
   - State checkpoints
   - File: `jd_threads.sqlite`

4. **Vector Database (FAISS/Chroma)**: Company content storage 🆕
   - **Purpose**: Store scraped company website content
   - **Type**: FAISS (default, local) or Chroma (optional)
   - **Storage**: By company name with metadata (URLs, scrape date, interval)
   - **Location**: `vector_store/` directory
   - **Features**:
     - Semantic search for company-specific content
     - Automatic deduplication by company name
     - Interval-based re-scraping support
   - **Modular**: Optional feature - system works without vector DB

### ORM Database (SQLAlchemy)

#### Models

**GoldStandard** (`database/models.py`)
- **Purpose**: Store accepted job descriptions
- **ORM Style**: Django-like declarative models
- **Fields**: id, user_id, job_title, job_body_json, config_json, created_at, updated_at
- **Indexes**: (user_id, job_title) for fast lookups

**UserFeedback** (`database/models.py`)
- **Purpose**: Store user feedback (accept/reject/edit/gripe)
- **Fields**: id, user_id, job_title, feedback_type, feedback_text, job_body_json, created_at
- **Indexes**: (user_id, feedback_type) for filtering

**Interaction** (`database/models.py`)
- **Purpose**: Complete history of all user actions
- **Fields**: id, user_id, session_id, interaction_type, job_title, input_data (JSON), output_data (JSON), metadata_json (JSON, returned as `metadata` in API), created_at
- **Indexes**: (user_id, created_at) for chronological queries

#### Usage

```python
from database.models import get_db_manager

db = get_db_manager()

# Save gold standard
gold_id = db.save_gold_standard(user_id, job_title, job_body_json, config_json)

# Retrieve gold standards
standards = db.get_gold_standards(user_id, job_title="Engineer", limit=10)

# Save feedback
feedback_id = db.save_user_feedback(user_id, "rejected", "Too formal", job_title)
```

### LangGraph Store System

#### Store Types

**InMemoryStore** (Default)
- **Location**: `langgraph.store.memory.InMemoryStore`
- **Use Case**: Development and testing
- **Persistence**: In-memory only (lost on restart)
- **Activation**: Automatic when using blackboard architecture

**PostgresStore** (Production)
- **Location**: `langgraph.store.postgres.PostgresStore`
- **Use Case**: Production deployments
- **Persistence**: Persistent across restarts
- **Activation**: Set `use_persistent_store=True` in `build_job_graph()`

#### Namespaces

Memories are organized by namespaces (tuples):

- **Gold Standards**: `(user_id, "gold_standard")`
  - Key: job_title
  - Value: `{"body": job_body_json, "config": config_json}`

- **User Gripes**: `(user_id, "user_gripes")`
  - Key: unique ID per gripe
  - Value: `{"feedback": text, "type": "rejected"|"edited", "job_title": title}`

#### Store Operations

```python
# Put memory
store.put((user_id, "gold_standard"), job_title, {"body": job_body_json})

# Search memories (supports semantic search if configured)
memories = store.search((user_id, "gold_standard"), query="engineer", limit=5)

# Get specific memory
memory = store.get((user_id, "gold_standard"), job_title)

# List all keys in namespace
keys = store.list((user_id, "gold_standard"), limit=10)
```

### Data Synchronization

The system automatically syncs data between ORM database and LangGraph store:

1. **Before Graph Execution**: `sync_all_to_store()` copies:
   - Gold standards → Store namespace `(user_id, "gold_standard")`
   - User gripes → Store namespace `(user_id, "user_gripes")`

2. **During Graph Execution**: Experts access store directly
   - Generator Expert searches for gold standards
   - Style Expert searches for user gripes

3. **After Feedback**: Data saved to both:
   - ORM database (for UI/history)
   - LangGraph store (for next graph run)

### Accessing Data

- **Via UI**: Sidebar → History & Data tabs
- **Via Code**: 
  - ORM: `DatabaseManager` from `database.models`
  - Store: Access via `store` parameter in graph nodes
- **Location**: Databases in project root directory

### Semantic Search (Optional)

To enable semantic search in the store:

```python
from langchain.embeddings import init_embeddings

store = InMemoryStore(
    index={
        "embed": init_embeddings("openai:text-embedding-3-small"),
        "dims": 1536,
        "fields": ["$"]  # Embed all fields
    }
)
```

This allows natural language queries like:
```python
memories = store.search(
    (user_id, "gold_standard"),
    query="What are good examples for software engineer roles?",
    limit=3
)
```

---

## User Feedback System

### Feedback Types

1. **Accept** ✅
   - **Action**: Saves job description as gold standard
   - **Storage**: `gold_standards` table
   - **Usage**: Used by Generator Expert in future generations
   - **Location**: Below preview panel

2. **Reject** ❌
   - **Action**: Saves rejection feedback
   - **Storage**: `user_feedback` table (type: 'rejected')
   - **Usage**: Used by Style Expert to avoid similar issues
   - **Requires**: Feedback text

3. **Edit** ✏️
   - **Action**: Saves edit feedback
   - **Storage**: `user_feedback` table (type: 'edited')
   - **Usage**: Used by Style Expert to improve future outputs
   - **Requires**: Feedback text

### Targeted Feedback Application

**New Feature**: Apply feedback directly to specific sections without regenerating the entire job description.

#### How It Works

1. **Enter Feedback**: Type your feedback in the "Reject/Edit feedback" text area
   - Example: "Make the footer more ambitious and longer"
   - Example: "The description should be more technical"
   - Example: "Requirements need to emphasize leadership skills"

2. **Select Target Section**: Choose which section to update from the dropdown:
   - **Title**: Job headline/title
   - **Caption**: Subtitle/intro text
   - **Description**: Main job description text
   - **Requirements**: Requirements section
   - **Duties**: Duties/responsibilities section
   - **Benefits**: Benefits section
   - **Footer**: Closing text

3. **Apply Update**: Click "Apply feedback update" button
   - System uses LLM to rewrite only the selected section based on your feedback
   - Other sections remain unchanged
   - Updates happen immediately in the preview

#### Use Cases

- **Quick Edits**: "Make footer more ambitious" → Updates only footer
- **Section Refinement**: "Add more technical details" → Updates only description
- **Tone Adjustments**: "Make requirements less formal" → Updates only requirements
- **Content Expansion**: "Add more detail about daily tasks" → Updates only duties

#### Benefits

- **Faster**: No need to regenerate entire job description
- **Precise**: Only the section you want to change is updated
- **Preserves Context**: Other sections remain exactly as they were
- **Iterative**: Can apply multiple feedback updates to different sections

### Feedback Flow

```
User Action → Database Storage → Blackboard Memory → Future Generations
```

### Viewing Feedback

- **Location**: Sidebar → History & Data → Feedback tab
- **Shows**: All feedback with timestamps and job titles
- **Filter**: By feedback type (accepted/rejected/edited)

---

## UI Components

### Main Interface

#### Content Editor (Left Panel)
- Job title input with AI button
- Caption/subtitle text area
- AI-powered fields for:
  - Job Description
  - Requirements
  - Duties
  - Benefits
  - Footer
- "Generate Full Job Description" button

#### Advertisement Preview (Right Panel)
- Real-time preview of job advertisement
- Formatted display with:
  - Header placeholder
  - Job title and intro
  - Description
  - Requirements and Duties (side by side)
  - Benefits
  - Map placeholder
  - Footer
  - Apply buttons
- Conversation log

#### Feedback Panel (Below Preview)
- **Accept button**: Saves job as gold standard
- **Feedback text area**: Enter feedback for reject/edit or targeted updates
- **Reject button**: Saves rejection feedback
- **Edit button**: Saves edit feedback
- **Targeted Update** (New):
  - Section selector dropdown (Title, Caption, Description, Requirements, Duties, Benefits, Footer)
  - "Apply feedback update" button to update only selected section

### Sidebar

#### Generation Settings
- All configuration options
- Temperature calculation display
- RULER settings

#### Company Scraping 🆕
- **Enable Company Scraping**: Toggle to enable/disable scraping feature
- **URL Input**: Enter up to 3 company URLs to scrape
- **Scraping Interval**: Select how often to re-scrape (daily, weekly, bi-weekly, monthly, quarterly)
- **Company Name**: Auto-detected from URL (can be overridden)
- **Save Configuration**: Save scraping settings for future use
- **Manual Scrape**: Scrape immediately without saving configuration
- **Saved Configurations**: View and manage all saved company scraping configurations
- **Modular Design**: Feature is optional - blackboard architecture works without it

#### History & Data
- **Gold Standards Tab**: View and load previous accepted jobs
- **Feedback Tab**: View all user feedback
- **History Tab**: Complete interaction history

### Navigation Bar
- REFLINE header
- Navigation tabs (Detail, Content, Publications, Applications, History)
- User info display

### Chat Interface
- **Status**: Removed from UI
- **Note**: Chat functionality has been removed from the interface

---

## Activation/Deactivation Guide

### Quick Reference

| Feature | Location | Default | Requires |
|---------|----------|---------|----------|
| Advanced Generation | Sidebar → Generation Settings | ON | - |
| Blackboard Architecture | Automatic | Always ON | Advanced Generation |
| RULER Ranking | Sidebar → Generation Settings | OFF | Advanced Generation |
| Company Scraping 🆕 | Sidebar → Company Scraping | OFF | Optional |
| Feedback System | Below Preview | Always ON | - |
| History Panel | Sidebar | Always ON | - |
| Database Storage | Automatic | Always ON | - |
| Vector Database 🆕 | Automatic | Optional | Company Scraping |

### Step-by-Step Activation

#### Enable Advanced Generation
1. Open sidebar
2. Find "⚙️ Generation Settings"
3. Check "Use Advanced Generation"
4. Configure parameters as needed

#### Enable RULER Ranking
1. Enable Advanced Generation (see above)
2. Check "Use RULER Ranking"
3. Adjust "Number of Candidates" slider (2-5)
4. Generate job description

#### Blackboard Architecture
- **Status**: Automatically enabled when Advanced Generation is on
- **How it works**: When you enable Advanced Generation, the system automatically uses the blackboard architecture with multi-expert workflow
- **No configuration needed**: The system learns from your feedback automatically

#### Enable Company Scraping 🆕
1. Open sidebar → **🏢 Company Scraping** section
2. Check **"Enable Company Scraping"**
3. Enter 1-3 company URLs
4. (Optional) Set scraping interval
5. Click **"💾 Save Scraping Config"** or **"🔄 Scrape Now"**
6. Scraped content will be available for Style Expert during generation

#### Disable Features
- Uncheck the corresponding checkbox
- System falls back to simpler generation mode

### Feature Dependencies

```
Simple Generation
    ↓
Advanced Generation (enables configurable parameters + Blackboard Architecture)
    ↓
    ├─→ RULER Ranking (optional, for quality)
    └─→ Company Scraping (optional, for company-specific content) 🆕
        └─→ Vector Database (automatic when scraping enabled)
```

### Performance Considerations

| Mode | Speed | Quality | Cost | Learning |
|------|-------|---------|------|----------|
| Simple | Fast | Good | Low | No |
| Advanced (Blackboard) | Medium | Better | Medium | Yes |
| Advanced + RULER | Slow | Best | High | Yes |
| Advanced + Scraping 🆕 | Medium | Better+ | Medium | Yes |
| Advanced + RULER + Scraping 🆕 | Slow | Best+ | High | Yes |

### Recommended Settings

#### For Quick Generation
- Advanced Generation: ON
- RULER: OFF
- Company Scraping: OFF (optional)
- (Blackboard automatically enabled)

#### For Best Quality
- Advanced Generation: ON
- RULER: ON (3-5 candidates)
- Company Scraping: ON (for company-specific content)
- (Blackboard automatically enabled)

#### For Learning System
- Advanced Generation: ON
- RULER: ON (optional)
- Company Scraping: ON (optional, for company context)
- Provide feedback on generated jobs (Blackboard learns automatically)

#### For Company-Specific Content 🆕
- Advanced Generation: ON
- Company Scraping: ON
- Configure company URLs and scraping interval
- Style Expert will use scraped content for refinement

---

## Temperature Calculation

The system automatically calculates LLM temperature based on configuration:

### Base Temperature
- **Formal**: 0.20
- **Neutral**: 0.35
- **Casual**: 0.55

### Adjustments
- **Startup**: +0.05
- **Public Sector**: -0.05
- **Senior/Lead/Principal**: -0.05
- **Intern/Junior**: +0.05
- **Finance/Healthcare/Public IT**: -0.05
- **AI Startup/Ecommerce**: +0.05

### Final Range
- **Clamped**: Between 0.10 and 0.75
- **Display**: Shown in sidebar when Advanced Generation is enabled

---

## Troubleshooting

### Database Issues
- **Location**: Check project root for `.sqlite` files
- **Reset**: Delete database files to start fresh
- **Backup**: Copy `.sqlite` files to backup location

### Blackboard Not Working
- Ensure "Use Advanced Generation" is enabled (Blackboard is automatic)
- Verify database files exist and are writable
- Check console for error messages
- Ensure store sync is working (check database/store_sync.py)

### RULER Not Working
- Ensure "Use Advanced Generation" is enabled
- Check that "Use RULER Ranking" is checked
- Verify API keys are set correctly
- Check judge model availability

### Company Scraping Not Working 🆕
- Ensure "Enable Company Scraping" is checked in sidebar
- Verify URLs are valid and accessible
- Check that `beautifulsoup4` and `lxml` are installed
- Verify `faiss-cpu` is installed for vector storage
- Check OpenAI API key is set (required for embeddings)
- Review error messages in console
- System continues without scraping if it fails (modular design)

### Preview Not Updating
- Refresh browser page
- Check that session state is being updated
- Verify no errors in browser console
- Try generating again

---

## Advanced Configuration

### Custom User ID
- **Default**: "default"
- **Change**: Set `st.session_state.user_id` in code
- **Use Case**: Multi-user scenarios, user-specific gold standards

### Database Paths
- **ORM DB**: `jd_database.sqlite` (configurable in `get_db_manager()`)
- **Threads DB**: `jd_threads.sqlite` (configurable in `build_job_graph()`)
- **Store**: InMemoryStore (default, in-memory) or PostgresStore (production)
- **Vector Store**: `vector_store/` directory (FAISS or Chroma) 🆕
- **Scraper Config**: `company_scraper_config.json` (scraping configurations) 🆕

### Judge Model
- **Default**: `openai/o3-mini`
- **Change**: Modify `judge_model` parameter in `generate_best_job_body_with_ruler()`
- **Options**: Any OpenAI-compatible model

---

## Best Practices

1. **Start Simple**: Begin with Advanced Generation, add RULER/Blackboard as needed
2. **Provide Feedback**: Accept good jobs, reject/edit bad ones to improve system
3. **Use Gold Standards**: Load previous accepted jobs as starting points
4. **Monitor History**: Review interaction history to understand system behavior
5. **Adjust Settings**: Fine-tune parameters based on your industry and needs
6. **Backup Databases**: Regularly backup `.sqlite` files for data safety

---

## Recent Feature Updates

### Benefits Restriction (Implemented)
- **Strict Keyword Enforcement**: Benefits section now only uses the exact keywords provided in "Benefit Keywords" field
- **No Additional Benefits**: System will not add any benefits beyond what you specify
- **Empty if None**: If no benefit keywords are provided, benefits section will be empty
- **Post-Processing Filter**: Generated benefits are filtered to ensure only provided keywords are included
- **One-to-One Mapping**: Creates exactly one benefit per keyword provided

### Benefit Keywords Parsing (Implemented)
- **Flexible Input Format**: Supports both comma-separated and newline-separated formats
- **Examples**:
  - Comma-separated: `"hybrid work in Switzerland, continuing education in AI and ML"`
  - Newline-separated: One keyword per line
  - Mixed: Can combine both formats

### Targeted Feedback Application (Implemented)
- **Section-Specific Updates**: Apply feedback to individual sections without regenerating entire job
- **Quick Iterations**: Make precise edits to specific sections (e.g., "make footer more ambitious")
- **Preserves Context**: Other sections remain unchanged during targeted updates
- **Available Sections**: Title, Caption, Description, Requirements, Duties, Benefits, Footer

### Company Scraping Feature (Implemented) 🆕
- **Website Scraping**: Scrape up to 3 company URLs for company-specific content
- **Vector Database Storage**: Store scraped content in FAISS vector database by company name
- **Configurable Intervals**: Set scraping frequency (daily, weekly, monthly, quarterly)
- **Persistent Storage**: Scraped content persists across sessions
- **Semantic Search**: Retrieve relevant company content using natural language queries
- **Modular Design**: Completely optional - blackboard architecture works without it
- **Integration**: Scraped content available to Style Expert for refining job descriptions
- **UI Integration**: Full configuration panel in sidebar with save/load functionality

### Gold Standards Usage (Implemented) 🆕
- **Few-Shot Learning**: Gold standards are now used as examples in generation prompts
- **Smart Matching**: Matches by job title similarity and config (company type, industry, formality)
- **Company Identity**: Maintains company style across different job types
- **Job-Specific Adaptation**: Adapts content to current job while preserving style
- **Graceful Fallback**: Works perfectly without gold standards (no examples added)
- **Context Engineering**: Properly structured prompt with conditional examples section

### RULER-Based Refinement (Implemented) 🆕
- **Test-Time Compute**: RULER scores candidates before refinement
- **Quality Threshold**: Candidates scoring below 0.7 are flagged for refinement
- **Selective Refinement**: Only refines candidates that need improvement
- **Score Storage**: RULER scores stored in state for Style Expert decisions

### HITL-Based Refinement (Implemented) 🆕
- **Human-in-the-Loop**: Refinement primarily driven by user feedback from UI
- **Job-Specific Priority**: Prioritizes feedback for similar job titles
- **Store Integration**: Retrieves historical feedback from LangGraph store
- **Conditional Refinement**: Only refines when actual user feedback exists
- **No Automatic Loops**: Refinement is intentional, not automatic

### Less Sequential Architecture (Implemented) 🆕
- **Conditional Edges**: Workflow uses conditional edges instead of strict sequential flow
- **RULER Scorer Node**: Separate node for scoring (test-time compute)
- **Conditional Refinement**: Style Expert only runs if HITL feedback or RULER indicates need
- **Flexible Flow**: Can skip refinement if not needed, making architecture less sequential

## Company Scraping Feature 🆕

### Overview

The company scraping feature allows you to scrape company websites and store the content in a vector database for use in job description generation. This enables the Style Expert to refine job descriptions based on company-specific information.

### Features

- **URL Input**: Enter up to 3 company URLs to scrape
- **Automatic Company Detection**: Company name extracted from URL domain
- **Vector Storage**: Content stored in FAISS vector database by company name
- **Configurable Intervals**: Set scraping frequency (daily, weekly, monthly, etc.)
- **Persistent Storage**: Scraped content persists across sessions
- **Semantic Search**: Retrieve relevant company content using natural language queries
- **Modular Design**: Completely optional - blackboard architecture works without it

### Activation

1. Open sidebar → **🏢 Company Scraping** section
2. Check **"Enable Company Scraping"**
3. Enter 1-3 company URLs
4. Select scraping interval
5. Click **"💾 Save Scraping Config"** to save for future use
   - OR click **"🔄 Scrape Now"** for one-time scraping

### Configuration Options

#### Scraping Interval
- **Daily**: Re-scrape every day
- **Weekly**: Re-scrape every 7 days (default)
- **Bi-weekly**: Re-scrape every 14 days
- **Monthly**: Re-scrape every 30 days
- **Quarterly**: Re-scrape every 90 days

#### Company Name
- **Auto-detected**: Extracted from first URL domain
- **Override**: Manually specify company name if needed

### How It Works

1. **Scraping**: When URLs are provided, the system scrapes content from all URLs
2. **Storage**: Content is stored in vector database under company name
3. **Retrieval**: During job generation, scraped content is retrieved from vector store
4. **Usage**: Content is available to Style Expert for refining job descriptions
5. **Re-scraping**: System checks interval and re-scrapes when due

### Integration with Blackboard Architecture

The scraping feature integrates seamlessly with the blackboard architecture:

```
START → Scrape Company (retrieves from vector DB or scrapes if needed)
    ↓
Generator Expert (uses gold standards as few-shot examples)
    ↓
RULER Scorer (test-time compute - scores all candidates)
    ↓
[Conditional] → Style Expert (if HITL feedback OR low RULER scores)
    - Uses user gripes (HITL feedback)
    - Uses scraped company content (style consistency)
    - Uses RULER scores (quality issues)
    OR
    ↓
RULER Curator (selects best using existing scores)
    ↓
END
```

### Vector Database

#### FAISS (Default)
- **Type**: Local file-based vector store
- **Location**: `vector_store/faiss_index/`
- **Advantages**: 
  - No server required
  - Fast local access
  - Perfect for MVP
- **Installation**: `pip install faiss-cpu`

#### Chroma (Alternative)
- **Type**: Persistent vector database
- **Location**: `vector_store/chroma/`
- **Advantages**:
  - Better for production
  - Supports metadata filtering
- **Installation**: `pip install chromadb`
- **Activation**: Uncomment in `requirements.txt` and set `store_type="chroma"`

### Storage Structure

Content is stored with the following metadata:
- **Company Name**: Identifier for the company
- **URLs**: List of scraped URLs
- **Scrape Date**: When content was last scraped
- **Interval**: Scraping interval setting
- **Content**: Full text of scraped pages

### Usage in Code

```python
from services.company_scraper import get_scraper_manager

# Get scraper manager
scraper_manager = get_scraper_manager()

# Scrape company URLs
content = scraper_manager.scrape_company_from_urls(
    urls=["https://example.com/about", "https://example.com/careers"],
    company_name="example"
)

# Retrieve company content
content = scraper_manager.get_company_content(
    company_name="example",
    query="company culture and values",  # Optional semantic search
    k=5  # Number of results
)
```

### Troubleshooting

#### Scraping Fails
- **Check URLs**: Ensure URLs are accessible and valid
- **Network**: Verify internet connection
- **Dependencies**: Install `beautifulsoup4` and `lxml`
- **Error Handling**: System continues without scraping if it fails (modular design)

#### Vector Store Not Working
- **Installation**: Ensure `faiss-cpu` is installed: `pip install faiss-cpu`
- **Permissions**: Check write permissions for `vector_store/` directory
- **Embeddings**: Verify OpenAI API key is set for embeddings

#### Content Not Retrieved
- **Check Storage**: Verify content was scraped and stored
- **Company Name**: Ensure company name matches between scraping and retrieval
- **Vector Store**: Check if vector store is initialized correctly

### Best Practices

1. **Start with Key Pages**: Scrape about, careers, and company culture pages
2. **Set Appropriate Intervals**: Weekly or monthly is usually sufficient
3. **Use Saved Configurations**: Save frequently used company scraping settings
4. **Monitor Storage**: Vector store grows over time - monitor disk usage
5. **Test Scraping**: Use "Scrape Now" button to test before saving configuration

---

## Future Enhancements

Planned features (not yet implemented):
- ~~Company scraping from URLs~~ ✅ **IMPLEMENTED**
- Style profile generation
- Consistency reporting
- Multi-language support expansion
- Advanced style refinement using style_llm (using scraped content)
- Export/import of gold standards
- User authentication and multi-user support
- Scheduled scraping (cron job) for production deployments

