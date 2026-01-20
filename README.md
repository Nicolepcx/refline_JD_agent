# Job Description Writer - Multi-Agent System

A Streamlit-based application for creating and editing job advertisements with AI assistance. The app uses LLM (Qwen/Qwen3-32B-fast via Nebius) to help generate and improve job description content.

## Features

- **AI-Powered Content Generation**: Generate and improve job descriptions, requirements, duties, and benefits using AI
- **Interactive Chat Agent**: Chat with an AI agent that can update different sections of the job ad
- **Live Preview**: See a real-time preview of the job advertisement as you edit
- **Modular Architecture**: Clean, maintainable code structure with separated concerns

## Setup

### Prerequisites

- Python 3.11 or higher
- A `.env` file with your Nebius API key:
  ```
  NEBIUS_API_KEY=your_api_key_here
  ```

### Installation

1. **Create a virtual environment** (optional but recommended):
   ```bash
   python -m venv refline_JD
   source refline_JD/bin/activate  # On Windows: refline_JD\Scripts\activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**:
   Create a `.env` file in the project root with:
   ```
   NEBIUS_API_KEY=your_nebius_api_key
   ```

## Running the Application

```bash
streamlit run app.py
```

The application will open in your default web browser at `http://localhost:8501`

## Project Structure

```
JD_writer_MAS/
├── app.py                 # Main Streamlit application entry point
├── config.py              # Configuration and default job data
├── llm_service.py         # LLM initialization and API calls
├── agent.py               # Agent chat handler and intent routing
├── utils.py               # Utility functions (text formatting, conversions)
├── models/                # Pydantic data models
│   ├── __init__.py        # Package initialization
│   └── job_models.py      # JobBody, JobGenerationConfig, SkillItem models
├── generators/            # Job generation logic
│   ├── __init__.py        # Package initialization
│   └── job_generator.py   # render_job_body, generate_job_body_candidate
├── ruler/                 # RULER-based quality evaluation
│   ├── __init__.py        # Package initialization
│   └── ruler_utils.py     # RULER trajectory conversion and ranking
├── services/              # High-level service layer
│   ├── __init__.py        # Package initialization
│   ├── job_service.py     # generate_full_job_description, generate_job_section
│   └── graph_service.py   # LangGraph blackboard workflow integration
├── database/              # Database and storage
│   ├── __init__.py        # Package initialization
│   ├── models.py          # SQLAlchemy ORM models (Django-style)
│   └── store_sync.py      # Sync ORM data to LangGraph store
├── graph/                 # LangGraph workflow
│   ├── __init__.py        # Package initialization
│   └── job_graph.py       # Blackboard architecture with multi-expert workflow
├── helpers/               # Helper functions
│   ├── __init__.py        # Package initialization
│   └── config_helper.py   # Session state to JobGenerationConfig conversion
├── ui/                    # UI components package
│   ├── __init__.py        # Package initialization
│   ├── components.py      # Reusable UI components (ai_field, etc.)
│   ├── layout.py          # Layout rendering functions (header, nav, preview)
│   ├── config_panel.py    # Configuration sidebar UI
│   └── feedback_panel.py  # Feedback buttons and history panel
├── requirements.txt       # Python dependencies
├── README.md              # This file
├── Features.md            # Features and configuration guide
├── Architecture.md        # Visual architecture diagrams (Mermaid)
└── memory.md              # Database and memory architecture details
```

## Component Descriptions

### `app.py`
The main entry point for the Streamlit application. Orchestrates the UI layout and initializes session state.

### `config.py`
- **Purpose**: Centralized configuration management
- **Contents**:
  - Environment variable loading (NEBIUS_API_KEY)
  - Default job advertisement data structure
  - Default values for all job fields

### `llm_service.py`
- **Purpose**: LLM integration and API communication
- **Key Functions**:
  - `get_base_llm()`: Initializes and caches the base ChatOpenAI instance (writer)
  - `get_judge_llm()`: Initializes and caches the judge LLM (for RULER)
  - `get_style_llm()`: Initializes and caches the style LLM (for refinement)
  - `call_llm()`: Makes API calls to generate/improve text based on instructions

### `models/job_models.py`
- **Purpose**: Pydantic data models for type safety and validation
- **Key Models**:
  - `SkillItem`: Represents a skill with name, category, and level
  - `JobBody`: Structured job description with description, requirements, benefits, duties, summary
  - `JobGenerationConfig`: Configuration for job generation with industry defaults, temperature calculation

### `generators/job_generator.py`
- **Purpose**: Core job description generation logic
- **Key Functions**:
  - `render_job_body()`: Main generator that creates structured JobBody from config
  - `generate_job_body_candidate()`: Generate candidates with temperature jitter
  - `explain_temperature()`: Debug function to explain temperature calculation

### `ruler/ruler_utils.py`
- **Purpose**: RULER-based quality evaluation and ranking
- **Key Functions**:
  - `jd_candidate_to_trajectory()`: Convert JobBody to RULER trajectory format
  - `generate_best_job_body_with_ruler()`: Generate multiple candidates and rank them using RULER

### `services/job_service.py`
- **Purpose**: High-level service layer bridging simple and advanced generation
- **Key Functions**:
  - `generate_full_job_description()`: Generate complete job description (simple or advanced)
  - `generate_job_section()`: Generate or improve specific sections

### `agent.py`
- **Purpose**: Handles chat interactions with the AI agent
- **Key Functions**:
  - `handle_agent_chat()`: Processes user chat input and routes intents to appropriate job fields
  - Intent detection for: job description, requirements, duties, benefits

### `utils.py`
- **Purpose**: General utility functions and format conversions
- **Key Functions**:
  - `bullets()`: Converts multi-line text to markdown bullet points
  - `job_body_to_dict()`: Convert JobBody model to dictionary format
  - `dict_to_job_body()`: Convert dictionary to JobBody model

### `ui/components.py`
- **Purpose**: Reusable Streamlit UI components
- **Key Components**:
  - `ai_field()`: Text area with integrated AI button for generating content

### `ui/layout.py`
- **Purpose**: UI layout and rendering functions
- **Key Functions**:
  - `render_header()`: Top navigation bar
  - `render_title()`: Page title
  - `render_navigation()`: Tab navigation
  - `render_chat_input()`: Chat interface
  - `render_content_editor()`: Left column form editor
  - `render_preview()`: Right column job ad preview

## Usage

1. **Edit Fields Directly**: Use the text inputs and text areas in the "Content editor" section
2. **Use AI Buttons**: Click "Use AI" next to any field to generate or improve content
3. **Chat with Agent**: Use the "Chat with the Agent" input to:
   - Ask questions about the job ad
   - Request updates to specific sections (e.g., "update requirements", "improve job description")
   - Get general advice and suggestions
4. **Preview**: See the formatted job advertisement in real-time in the preview panel

## Dependencies

See `requirements.txt` for the complete list. Key dependencies include:
- `streamlit`: Web application framework
- `langchain`: LLM integration framework
- `langchain-openai`: OpenAI-compatible API client
- `langgraph`: Graph-based workflow orchestration
- `openpipe-art`: ART RULER for quality evaluation
- `pydantic`: Data validation and settings management
- `python-dotenv`: Environment variable management

## Advanced Features

### Job Generation Configuration

The application supports advanced job generation using `JobGenerationConfig`:
- **Language**: English or German
- **Formality**: Casual, neutral, or formal tone
- **Company Type**: Startup, scaleup, corporate, public sector, agency, consulting
- **Industry**: Generic, finance, healthcare, public IT, AI startup, ecommerce, manufacturing
- **Seniority**: Intern, junior, mid, senior, lead, principal
- **Skills**: List of required skills with categories and levels
- **Benefits**: Custom benefit keywords that get incorporated naturally

### RULER Quality Evaluation

The system can generate multiple job description candidates and use RULER (Reward Understanding for Language Model Evaluation and Ranking) to automatically select the best one based on quality metrics.

## Documentation

- **README.md**: This file - overview and setup instructions
- **Features.md**: Detailed feature documentation and configuration guide
- **Architecture.md**: Visual architecture diagrams using Mermaid (system overview, component relationships, data flows, workflows)
- **memory.md**: Database and memory architecture documentation

## Notes

- The application uses Nebius API with multiple models:
  - `Qwen/Qwen3-32B-fast`: Base writer and judge models
  - `google/gemma-2-9b-it-fast`: Style refinement model
- All LLM calls are cached using Streamlit's `@st.cache_resource` decorator
- Session state is used to persist job data and conversation history
- The system supports both simple LLM-based generation and advanced structured generation with configurable parameters
- For visual architecture diagrams, see `Architecture.md`