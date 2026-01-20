import streamlit as st
from services.job_service import generate_job_section
from helpers.config_helper import get_job_config_from_session
from config import DEFAULT_JOB_DATA
from llm_service import call_llm


def handle_agent_chat():
    """Callback for the 'Chat with the Agent' input."""
    q = st.session_state.get("agent_chat_input", "")
    if not q:
        return

    # Get current job context
    job_ctx = {k: st.session_state[k] for k in DEFAULT_JOB_DATA.keys()}
    st.session_state.messages.append({"role": "user", "content": q})

    lower_q = q.lower()
    
    # Check if advanced generation is enabled
    use_advanced = st.session_state.get("use_advanced_generation", True)
    config = get_job_config_from_session() if use_advanced else None
    job_title = st.session_state.get("job_headline", "")

    # Intent routing to fields
    if "job description" in lower_q or "generate full" in lower_q or "create job" in lower_q:
        if use_advanced and job_title:
            # Generate full job description using advanced method
            from services.job_service import generate_full_job_description
            use_ruler = st.session_state.get("use_ruler", False)
            num_candidates = st.session_state.get("ruler_num_candidates", 3)
            job_dict = generate_full_job_description(
                job_title, 
                config, 
                use_advanced=True,
                use_ruler=use_ruler,
                num_candidates=num_candidates
            )
            from helpers.config_helper import update_session_from_job_body
            update_session_from_job_body(job_dict)
            if use_ruler:
                answer = f"I generated {num_candidates} candidates, ranked them with RULER, and selected the best one. All sections have been filled."
            else:
                answer = "I generated a complete job description using advanced AI generation and filled all sections."
        else:
            new_desc = generate_job_section(
                "description", job_title, st.session_state.get("description", ""),
                job_ctx, config, use_advanced
            )
            st.session_state["description"] = new_desc
            answer = "I drafted the Job Description section and filled it into the form on the left."
        
    elif "requirement" in lower_q:
        new_req = generate_job_section(
            "requirements", job_title, st.session_state.get("requirements", ""),
            job_ctx, config, use_advanced
        )
        st.session_state["requirements"] = new_req
        answer = "I updated the Requirements section."
        
    elif "duty" in lower_q or "responsibilit" in lower_q:
        new_duty = generate_job_section(
            "duties", job_title, st.session_state.get("duties", ""),
            job_ctx, config, use_advanced
        )
        st.session_state["duties"] = new_duty
        answer = "I updated the Duties section."
        
    elif "benefit" in lower_q:
        new_benefits = generate_job_section(
            "benefits", job_title, st.session_state.get("benefits", ""),
            job_ctx, config, use_advanced
        )
        st.session_state["benefits"] = new_benefits
        answer = "I updated the Benefits section."
        
    else:
        # Default: general advisory answer, no field change
        answer = call_llm(
            "Answer the question about this job advertisement and suggest improvements.",
            "",
            job_ctx,
        )

    st.session_state.messages.append({"role": "assistant", "content": answer})
    st.session_state["agent_chat_input"] = ""

