"""
UI components for user feedback and history viewing.
"""
import streamlit as st
import json
from database.models import get_db_manager
from utils import job_body_to_dict
from models.job_models import JobBody
from config import DEFAULT_JOB_DATA
from helpers.config_helper import get_job_config_from_session
from llm_service import call_llm


def render_feedback_buttons(job_title: str, job_body_dict: dict):
    """Render feedback buttons (Accept, Reject, Edit) for the current job."""
    st.markdown("---")
    st.markdown("### Feedback")
    
    col1, col2, col3 = st.columns(3)
    
    user_id = st.session_state.get("user_id", "default")
    db = get_db_manager()
    
    # Convert to JobBody format for storage
    from models.job_models import JobBody
    from utils import dict_to_job_body
    
    try:
        job_body = dict_to_job_body(job_body_dict)
        job_body_json = job_body.model_dump_json(indent=2, ensure_ascii=False)
    except Exception:
        # Fallback to direct JSON
        job_body_json = json.dumps(job_body_dict, ensure_ascii=False, indent=2)
    
    with col1:
        if st.button("✅ Accept", use_container_width=True, type="primary"):
            # Save as gold standard
            config_json = None
            try:
                config = get_job_config_from_session()
                config_json = config.model_dump_json()
            except Exception:
                # If config can't be retrieved, continue without it
                pass
            
            gold_id = db.save_gold_standard(user_id, job_title, job_body_json, config_json)
            db.save_user_feedback(user_id, "accepted", job_title=job_title, job_body_json=job_body_json)
            db.save_interaction(
                user_id,
                "feedback",
                input_data={"job_title": job_title},
                output_data={"feedback_type": "accepted", "gold_id": gold_id},
                job_title=job_title
            )
            st.success("✅ Saved as gold standard!")
            st.rerun()
    
    with col2:
        feedback_text = st.text_area(
            "Reject/Edit feedback",
            key="feedback_text",
            height=80,
            placeholder="What would you like to change?"
        )
        # Optional targeted application of feedback to a specific section
        section_label_map = {
            "": None,
            "Description": "description",
            "Requirements": "requirements",
            "Duties": "duties",
            "Benefits": "benefits",
            "Footer": "footer",
            "Caption": "job_intro",
            "Title": "job_headline",
        }
        target_label = st.selectbox(
            "Apply feedback to section (optional)",
            list(section_label_map.keys()),
            key="feedback_target_section",
        )
        
        def _apply_feedback_update():
            """Callback to apply feedback to selected section."""
            target_section = section_label_map.get(st.session_state.get("feedback_target_section", ""))
            feedback_text_value = st.session_state.get("feedback_text", "")
            
            if not feedback_text_value.strip():
                st.session_state["feedback_error"] = "Please provide feedback text to apply."
                return
            elif not target_section:
                st.session_state["feedback_error"] = "Please choose a section to apply the feedback."
                return
            
            # Clear any previous error
            if "feedback_error" in st.session_state:
                del st.session_state["feedback_error"]
            
            try:
                ctx = {k: st.session_state.get(k, "") for k in DEFAULT_JOB_DATA.keys()}
                current_val = st.session_state.get(target_section, "")
                config = get_job_config_from_session()

                # Tailored, section-specific instructions to avoid overwriting other fields or adding long text
                section_label = st.session_state.get("feedback_target_section", "").lower() if st.session_state.get("feedback_target_section") else "section"
                section_specific_instruction = {
                    "job_headline": "Rewrite the job title with the feedback. Return a concise, single-line title only.",
                    "job_intro": "Rewrite ONLY the caption/subtitle (1-2 short sentences). Do not include other sections.",
                    "description": "Rewrite ONLY the main job description (2-4 sentences). No bullets.",
                    "requirements": "Rewrite ONLY the requirements as bullet points. 4-8 bullets. Nothing else.",
                    "duties": "Rewrite ONLY the duties/responsibilities as bullet points. 4-8 bullets. Nothing else.",
                    "benefits": "Rewrite ONLY the benefits as bullet points. One bullet per provided benefit keyword if present.",
                    "footer": "Rewrite ONLY the footer/closing line. Keep it short (1 sentence).",
                }.get(target_section, f"Update the {section_label} with the feedback.")

                instruction = (
                    f"{section_specific_instruction} "
                    f"Feedback to apply: '{feedback_text_value}'. "
                    "Keep tone consistent with the rest of the job ad. Return only the updated text for this section."
                )

                # Use direct LLM call with the custom instruction
                new_text = call_llm(instruction, current_val, ctx)
                # Set the value in session state (this is safe in a callback)
                st.session_state[target_section] = new_text
                st.session_state["feedback_success"] = f"Applied feedback to {st.session_state.get('feedback_target_section', 'selected section')}."
            except Exception as e:
                st.session_state["feedback_error"] = f"Error applying feedback: {str(e)}"
        
        st.button("Apply feedback update", use_container_width=True, key="apply_feedback_btn", on_click=_apply_feedback_update)
        
        # Display feedback messages if they exist
        if "feedback_success" in st.session_state:
            st.success(st.session_state.pop("feedback_success"))
            st.rerun()
        elif "feedback_error" in st.session_state:
            st.error(st.session_state.pop("feedback_error"))
    
    with col3:
        col_reject, col_edit = st.columns(2)
        with col_reject:
            if st.button("❌ Reject", use_container_width=True):
                if feedback_text:
                    job_body_json = job_body.model_dump_json(indent=2, ensure_ascii=False)
                    # Save to ORM database
                    db.save_user_feedback(
                        user_id, "rejected", feedback_text, job_title, job_body_json
                    )
                    db.save_interaction(
                        user_id,
                        "feedback",
                        input_data={"job_title": job_title, "feedback": feedback_text},
                        output_data={"feedback_type": "rejected"},
                        job_title=job_title
                    )
                    # Note: LangGraph store will be updated when graph runs with feedback_label="rejected"
                    st.success("Feedback saved. We'll avoid this in future generations.")
                    st.rerun()
                else:
                    st.warning("Please provide feedback text.")
        
        with col_edit:
            if st.button("✏️ Edit", use_container_width=True):
                if feedback_text:
                    job_body_json = job_body.model_dump_json(indent=2, ensure_ascii=False)
                    # Save to ORM database
                    db.save_user_feedback(
                        user_id, "edited", feedback_text, job_title, job_body_json
                    )
                    db.save_interaction(
                        user_id,
                        "feedback",
                        input_data={"job_title": job_title, "feedback": feedback_text},
                        output_data={"feedback_type": "edited"},
                        job_title=job_title
                    )
                    # Note: LangGraph store will be updated when graph runs with feedback_label="edited"
                    st.success("Edit feedback saved.")
                    st.rerun()
                else:
                    st.warning("Please provide feedback text.")


def render_history_panel():
    """Render panel for viewing history, gold standards, and feedback."""
    st.sidebar.markdown("---")
    st.sidebar.header("📊 History & Data")
    
    user_id = st.session_state.get("user_id", "default")
    db = get_db_manager()
    
    tab1, tab2, tab3 = st.sidebar.tabs(["Gold Standards", "Feedback", "History"])
    
    with tab1:
        st.subheader("Gold Standards")
        gold_standards = db.get_gold_standards(user_id, limit=10)
        
        if gold_standards:
            for gs in gold_standards:
                with st.expander(f"📌 {gs['job_title'][:50]}..."):
                    st.caption(f"Created: {gs['created_at']}")
                    col_load, col_delete = st.columns([1, 1])
                    with col_load:
                        if st.button("Load", key=f"load_gold_{gs['id']}", use_container_width=True):
                            try:
                                job_body_dict = json.loads(gs['job_body_json'])
                                from helpers.config_helper import update_session_from_job_body
                                update_session_from_job_body(job_body_dict)
                                st.success("Loaded into editor!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error loading: {e}")
                    with col_delete:
                        if st.button("🗑️ Delete", key=f"delete_gold_{gs['id']}", use_container_width=True, type="secondary"):
                            if db.delete_gold_standard(gs['id'], user_id):
                                st.success("Gold standard deleted!")
                                st.rerun()
                            else:
                                st.error("Failed to delete gold standard.")
        else:
            st.info("No gold standards yet. Accept a job description to create one.")
    
    with tab2:
        st.subheader("User Feedback")
        feedback = db.get_user_feedback(user_id, limit=20)
        
        if feedback:
            for fb in feedback:
                with st.expander(f"**{fb['feedback_type'].upper()}** - {fb.get('job_title', 'N/A')[:40]}..."):
                    if fb.get('feedback_text'):
                        st.write(fb['feedback_text'])
                    st.caption(f"Date: {fb['created_at']}")
                    if st.button("🗑️ Delete", key=f"delete_feedback_{fb['id']}", use_container_width=True, type="secondary"):
                        if db.delete_user_feedback(fb['id'], user_id):
                            st.success("Feedback deleted!")
                            st.rerun()
                        else:
                            st.error("Failed to delete feedback.")
        else:
            st.info("No feedback yet.")
    
    with tab3:
        st.subheader("Interaction History")
        history = db.get_interaction_history(user_id, limit=30)
        
        if history:
            for h in history:
                with st.expander(f"**{h['interaction_type'].upper()}** - {h.get('job_title', 'N/A')[:40]}..."):
                    if h.get('job_title'):
                        st.caption(f"Job: {h['job_title']}")
                    st.caption(f"Date: {h['created_at']}")
                    if st.button("🗑️ Delete", key=f"delete_interaction_{h['id']}", use_container_width=True, type="secondary"):
                        if db.delete_interaction(h['id'], user_id):
                            st.success("Interaction deleted!")
                            st.rerun()
                        else:
                            st.error("Failed to delete interaction.")
        else:
            st.info("No history yet.")

