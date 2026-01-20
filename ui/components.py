import streamlit as st
from services.job_service import generate_job_section
from helpers.config_helper import get_job_config_from_session
from config import DEFAULT_JOB_DATA
from llm_service import call_llm


def ai_field(label: str, key: str, instruction: str, height: int = 120):
    """
    Text area with a small AI button on the right.
    
    The AI button uses an on_click callback so it can safely update
    st.session_state[key] before the widget is instantiated.
    """
    def _run_ai():
        ctx = {k: st.session_state[k] for k in DEFAULT_JOB_DATA.keys()}
        current_value = st.session_state.get(key, "")
        job_title = st.session_state.get("job_headline", "")
        
        # Advanced generation with blackboard is always enabled
        config = get_job_config_from_session()
        
        # Map key to section name
        section_map = {
            "description": "description",
            "requirements": "requirements",
            "duties": "duties",
            "benefits": "benefits",
            "footer": "footer",
        }
        section = section_map.get(key, "description")
        
        if job_title:
            new_text = generate_job_section(
                section, job_title, current_value, ctx, config, use_advanced=True
            )
        else:
            new_text = call_llm(instruction, current_value, ctx)
        
        st.session_state[key] = new_text

    c1, c2 = st.columns([0.9, 0.1])

    with c1:
        # Ensure the value in session state is a string (handle cases where it might be a list or None)
        # Streamlit text_area requires string values
        current_value = st.session_state.get(key, "")
        if not isinstance(current_value, str):
            # Convert to string if it's not already
            if isinstance(current_value, list):
                current_value = "\n".join(str(item) for item in current_value)
            else:
                current_value = str(current_value) if current_value is not None else ""
            st.session_state[key] = current_value
        
        st.text_area(label, key=key, height=height)

    with c2:
        st.button(
            "Use AI",
            key=f"{key}_btn",
            on_click=_run_ai,
        )

