import streamlit as st
from utils import bullets
from config import DEFAULT_JOB_DATA
from llm_service import call_llm
from ui.components import ai_field


def render_header():
    """Render the top header bar."""
    st.markdown(
        """
        <div style="
            background-color:#234454;
            color:white;
            padding:6px 16px;
            font-family:system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            font-size:13px;
            display:flex;
            align-items:center;
            justify-content:space-between;">
            <div style="display:flex;align-items:center;gap:18px;">
                <span style="font-weight:600;letter-spacing:0.06em;">REFLINE</span>
                <span>Positions</span>
                <span>Talents</span>
                <span>Archive</span>
                <span>Employees</span>
                <span>Publications</span>
            </div>
            <div style="text-align:right;font-size:12px;">
                <div>Tester AG</div>
                <div style="opacity:0.85;">Nicole Königstein</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_title():
    """Render the title line with dynamic job title from session state."""
    # Get job title from session state, or show placeholder if empty
    job_title = st.session_state.get("job_headline", "")
    display_title = job_title if job_title else "Enter job title below first"
    
    st.markdown(
        f"""
        <div style="
            padding:8px 16px 4px 16px;
            font-family:system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
            <div style="font-size:16px;font-weight:600;{'color:#6b7280;font-style:italic;' if not job_title else ''}">
                {display_title}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_navigation():
    """Render the navigation tabs."""
    st.markdown(
        """
        <div style="
            padding:4px 16px 4px 16px;
            font-family:system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            font-size:13px;
            display:flex;
            gap:8px;">
            <span style="padding:4px 10px;border-radius:4px;border:1px solid #d1d5db;background-color:#f9fafb;">Detail</span>
            <span style="padding:4px 10px;border-radius:4px;border:1px solid #234454;background-color:#234454;color:white;">Content</span>
            <span style="padding:4px 10px;border-radius:4px;border:1px solid #d1d5db;background-color:#f9fafb;">Publications</span>
            <span style="padding:4px 10px;border-radius:4px;border:1px solid #d1d5db;background-color:#f9fafb;">Applications</span>
            <span style="padding:4px 10px;border-radius:4px;border:1px solid #d1d5db;background-color:#f9fafb;">History</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_chat_input(handle_agent_chat):
    """Render the chat input section."""
    label_col, input_col = st.columns([0.35, 0.65])
    with label_col:
        st.markdown(
            """
            <div style="
                margin-top:6px;
                font-size:18px;
                color:#f39729;
                font-weight:800;
                font-family:system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            ">
                Chat with the Agent
            </div>
            """,
            unsafe_allow_html=True,
        )

    with input_col:
        st.chat_input(
            "",
            key="agent_chat_input",
            on_submit=handle_agent_chat,
        )


def _run_async_stream(coro, on_item=None):
    """Helper to run async generators in Streamlit context.

    IMPORTANT: We must drain the async generator to completion.
    If we stop consuming early, LangGraph gets cancelled mid-run which shows up as
    ERROR/empty runs in tracing UIs (even if curator already yielded a result).

    Returns the final result item. Optionally accepts an on_item callback for streaming UI updates.
    """
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is running, use thread
            import threading
            
            result = None
            exception = None
            
            def run_in_thread():
                nonlocal result, exception
                try:
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    async def get_first_and_drain():
                        final = None
                        async for item in coro:
                            if on_item:
                                on_item(item)
                            # Accept both the legacy dict and typed result event
                            if isinstance(item, dict) and item.get("type") == "result":
                                final = item.get("data")
                            elif isinstance(item, dict) and "type" not in item:
                                final = item
                        return final

                    result = new_loop.run_until_complete(get_first_and_drain())
                    new_loop.close()
                except Exception as e:
                    exception = e
            
            thread = threading.Thread(target=run_in_thread)
            thread.start()
            thread.join()
            
            if exception:
                raise exception
            return result
        else:
            async def get_first_and_drain():
                final = None
                async for item in coro:
                    if on_item:
                        on_item(item)
                    if isinstance(item, dict) and item.get("type") == "result":
                        final = item.get("data")
                    elif isinstance(item, dict) and "type" not in item:
                        final = item
                return final

            return loop.run_until_complete(get_first_and_drain())
    except RuntimeError:
        # No event loop, create one
        async def get_first_and_drain():
            final = None
            async for item in coro:
                if on_item:
                    on_item(item)
                if isinstance(item, dict) and item.get("type") == "result":
                    final = item.get("data")
                elif isinstance(item, dict) and "type" not in item:
                    final = item
            return final

        return asyncio.run(get_first_and_drain())


def render_content_editor():
    """Render the left column content editor."""
    st.subheader("Content editor")
    
    # Generate full JD button (blackboard architecture always enabled)
    if st.button("🚀 Generate Full Job Description", use_container_width=True, type="primary", key="generate_full_jd"):
            job_title = st.session_state.get("job_headline", "")
            if job_title:
                from services.graph_service import generate_with_graph_stream
                from helpers.config_helper import get_job_config_from_session, update_session_from_job_body
                from database.models import get_db_manager
                import asyncio
                
                config = get_job_config_from_session()
                use_ruler = st.session_state.get("use_ruler", False)
                num_candidates = st.session_state.get("ruler_num_candidates", 3)
                user_id = st.session_state.get("user_id", "default")
                
                # Get company URLs from session state (if scraping is enabled)
                from ui.company_scraper_panel import get_company_urls_from_session
                company_urls = get_company_urls_from_session()
                
                # Create status container for streaming updates
                status_container = st.empty()
                last_node = None
                
                if use_ruler:
                    status_container.info(f"🔄 Generating with blackboard architecture and RULER ranking ({num_candidates} candidates)...")
                else:
                    status_container.info("🔄 Generating with blackboard architecture (multi-expert workflow)...")
                
                # Stream the generation and update UI immediately when result is available
                try:
                    from services.graph_service import generate_with_graph_stream
                    
                    def handle_stream_item(item):
                        nonlocal last_node
                        if isinstance(item, dict):
                            if item.get("type") == "progress":
                                node = item.get("node")
                                # Hide scrape progress when no scraping is enabled
                                if node == "scrape_company" and not company_urls:
                                    return
                                if node and node != last_node:
                                    status_container.info(f"🔄 {node}...")
                                    last_node = node

                    # Stream generation with live progress updates
                    job_dict = _run_async_stream(
                        generate_with_graph_stream(
                            job_title,
                            config,
                            user_id=user_id,
                            company_urls=company_urls if company_urls else None,
                        ),
                        on_item=handle_stream_item,
                    )
                    
                    if job_dict:
                        # Update session state immediately as content streams in
                        update_session_from_job_body(job_dict)
                        
                        # Store RULER rankings immediately
                        if "ruler_rankings" in job_dict:
                            st.session_state["last_ruler_rankings"] = job_dict.get("ruler_rankings", [])
                        if "ruler_score" in job_dict:
                            st.session_state["last_ruler_score"] = job_dict.get("ruler_score")
                        if "ruler_num_candidates" in job_dict:
                            st.session_state["last_ruler_num_candidates"] = job_dict.get("ruler_num_candidates", 0)
                        
                        # Log interaction
                        db = get_db_manager()
                        db.save_interaction(
                            user_id,
                            "generation",
                            input_data={"job_title": job_title, "config": config.model_dump()},
                            output_data=job_dict,
                            metadata={"method": "blackboard", "ruler_score": job_dict.get("ruler_score")},
                            job_title=job_title
                        )
                        
                        if use_ruler:
                            status_container.success(f"✅ Job description generated using RULER (best of {num_candidates} candidates)!")
                        else:
                            status_container.success("✅ Job description generated!")
                    else:
                        status_container.error("❌ No result generated")
                    
                except Exception as e:
                    status_container.error(f"❌ Generation failed: {str(e)}")
                    st.exception(e)
            else:
                st.warning("Please enter a job title first.")
    
    st.markdown("---")

    st.text_input("Job title", key="job_headline")

    st.text_area("Caption (subtitle)", key="job_intro", height=70)

    st.text_area("Job Description", key="description", height=160)
    st.text_area("Requirement", key="requirements", height=160)
    st.text_area("Duty", key="duties", height=160)
    st.text_area("Benefit", key="benefits", height=160)
    st.text_area("Footer", key="footer", height=70)


def render_preview():
    """Render the right column advertisement preview."""
    st.subheader("Advertisement preview")

    # Read latest values from session state - ensure we get fresh data each time
    job = {}
    for k in DEFAULT_JOB_DATA.keys():
        # Get from session state, fallback to default
        job[k] = st.session_state.get(k, DEFAULT_JOB_DATA.get(k, ""))

    # Header placeholder
    st.markdown(
        """
        <div style="
            width: 100%;
            height: 180px;
            background-color: #e5e7eb;
            border-radius: 6px 6px 0 0;
            border: 1px solid #d1d5db;
            border-bottom: none;
            display:flex;
            align-items:center;
            justify-content:center;
            color:#4b5563;
            font-size:0.9rem;">
            Header image placeholder
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Body
    st.markdown(
        """
        <div style="
            width: 100%;
            border-left: 1px solid #d1d5db;
            border-right: 1px solid #d1d5db;
            border-bottom: 1px solid #d1d5db;
            border-radius: 0 0 6px 6px;
            padding: 18px 24px 10px 24px;
            background-color: white;">
        """,
        unsafe_allow_html=True,
    )

    st.markdown(f"### {job['job_headline']}")
    st.write(job["job_intro"])

    if job["caption"].strip():
        st.write(job["caption"])

    if job["description"].strip():
        st.write(job["description"])

    col_req, col_duty = st.columns(2)

    with col_req:
        st.markdown("#### Requirement")
        st.markdown(bullets(job["requirements"]))

        st.markdown("#### Benefit")
        st.markdown(bullets(job["benefits"]))

    with col_duty:
        st.markdown("#### Duty")
        st.markdown(bullets(job["duties"]))

    # Map placeholder
    st.markdown(
        """
        <div style="
            width:100%;
            height:220px;
            margin-top:16px;
            background-color:#e5e7eb;
            border-radius:4px;
            border:1px solid #d1d5db;
            display:flex;
            align-items:center;
            justify-content:center;
            color:#4b5563;
            font-size:0.85rem;">
            Map placeholder
        </div>
        """,
        unsafe_allow_html=True,
    )

    if job["footer"].strip():
        st.markdown(
            f"<p style='margin-top:10px;font-size:0.85rem;color:#4b5563;'>{job['footer']}</p>",
            unsafe_allow_html=True,
        )

    c1, c2 = st.columns([0.15, 0.2])
    with c1:
        st.button("Apply", use_container_width=True)
    with c2:
        st.button("Apply with xeebo", use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)

