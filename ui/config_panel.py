"""
UI components for JobGenerationConfig settings.
"""
import streamlit as st
from models.job_models import JobGenerationConfig


def render_ruler_rankings():
    """Display RULER rankings in the sidebar if available."""
    rankings = st.session_state.get("last_ruler_rankings", [])
    best_score = st.session_state.get("last_ruler_score")
    num_candidates = st.session_state.get("last_ruler_num_candidates", 0)
    
    if (rankings and len(rankings) > 0) or (best_score is not None) or (num_candidates > 0):
        st.markdown("---")
        st.header("📊 RULER Rankings")
        
        if best_score is not None:
            st.metric("Best Score", f"{best_score:.3f}")
        
        if num_candidates > 0:
            st.caption(f"Evaluated {num_candidates} candidates")
        
        if rankings and len(rankings) > 0:
            st.markdown("#### Ranking Details")
            for ranking in rankings:
                rank = ranking.get("rank", 0)
                score = ranking.get("score", 0.0)
                preview = ranking.get("job_description_preview", "")
                
                # Color code: gold for rank 1, silver for rank 2, bronze for rank 3
                if rank == 1:
                    rank_emoji = "🥇"
                    rank_color = "#FFD700"  # Gold
                elif rank == 2:
                    rank_emoji = "🥈"
                    rank_color = "#C0C0C0"  # Silver
                elif rank == 3:
                    rank_emoji = "🥉"
                    rank_color = "#CD7F32"  # Bronze
                else:
                    rank_emoji = f"#{rank}"
                    rank_color = "#666666"
                
                with st.container():
                    st.markdown(
                        f"""
                        <div style="
                            padding: 8px;
                            margin-bottom: 8px;
                            border-left: 3px solid {rank_color};
                            background-color: {'#f0f0f0' if rank == 1 else '#fafafa'};
                            border-radius: 4px;
                        ">
                            <div style="font-weight: 600; color: {rank_color};">
                                {rank_emoji} Rank {rank} - Score: {score:.3f}
                            </div>
                            {f'<div style="font-size: 0.85em; color: #666; margin-top: 4px;">{preview}</div>' if preview else ''}
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
        else:
            st.caption("No ranking details available for this run.")


def _init_config_defaults():
    """Set default values for config widgets ONCE via setdefault.

    Using ``setdefault`` ensures we never overwrite a value the user (or a
    widget) already placed in session state, and we never mutate state during
    the render cycle — both of which can trigger unwanted Streamlit re-runs.
    """
    st.session_state.setdefault("use_advanced_generation", True)
    st.session_state.setdefault("use_ruler", False)
    st.session_state.setdefault("ruler_num_candidates", 3)
    st.session_state.setdefault("config_language", "en")
    st.session_state.setdefault("config_formality", "neutral")
    st.session_state.setdefault("config_company_type", "scaleup")
    st.session_state.setdefault("config_industry", "generic")
    st.session_state.setdefault("config_seniority_label", "")
    st.session_state.setdefault("config_min_years", 0)
    st.session_state.setdefault("config_max_years", 0)
    st.session_state.setdefault("config_skills", "")
    st.session_state.setdefault("config_benefit_keywords", "")


def render_config_sidebar():
    """Render the configuration sidebar.

    Widget values are managed entirely through ``st.session_state[key]``.
    We NEVER pass both ``value=`` and ``key=`` to the same widget — doing so
    is a Streamlit anti-pattern that can trigger extra re-runs / flicker.
    """
    _init_config_defaults()

    with st.sidebar:
        st.header("⚙️ Generation Settings")

        st.markdown("---")

        # RULER toggle
        # key-only — Streamlit reads the current value from session state
        use_ruler = st.checkbox(
            "Use RULER Ranking",
            key="use_ruler",
            help="Generate multiple candidates and use RULER to automatically select the best one (slower but higher quality)"
        )

        if use_ruler:
            st.slider(
                "Number of Candidates",
                min_value=2,
                max_value=5,
                key="ruler_num_candidates",
                help="More candidates = better quality but slower generation"
            )

        st.markdown("---")

        # Language
        st.selectbox(
            "Language",
            options=["en", "de"],
            key="config_language",
            help="Language for the job description"
        )

        # Formality
        st.selectbox(
            "Tone / Formality",
            options=["casual", "neutral", "formal"],
            key="config_formality",
            help="Tone of the job description"
        )

        # Company Type
        _company_types = [
            "startup", "scaleup", "sme", "corporate", "public_sector",
            "social_sector", "agency", "consulting", "hospitality", "retail",
        ]
        st.selectbox(
            "Company Type",
            options=_company_types,
            key="config_company_type",
            format_func=lambda x: {
                "startup": "Startup",
                "scaleup": "Scaleup",
                "sme": "SME / KMU",
                "corporate": "Corporate",
                "public_sector": "Public Sector",
                "social_sector": "Social Sector / Stiftung",
                "agency": "Agency",
                "consulting": "Consulting",
                "hospitality": "Hospitality / Gastronomie",
                "retail": "Retail / Detailhandel",
            }.get(x, x),
            help="Type of company/organization"
        )

        # Industry
        st.selectbox(
            "Industry",
            options=["generic", "finance", "healthcare", "social_care", "public_it", "ai_startup", "ecommerce", "manufacturing"],
            key="config_industry",
            help="Industry sector"
        )

        # Seniority
        st.selectbox(
            "Seniority Level",
            options=["", "intern", "junior", "mid", "senior", "lead", "principal"],
            key="config_seniority_label",
            format_func=lambda x: "Not specified" if x == "" else x.title(),
            help="Seniority level for the role"
        )

        # Experience years
        col1, col2 = st.columns(2)
        with col1:
            st.number_input(
                "Min Years Experience",
                min_value=0,
                max_value=20,
                key="config_min_years",
                help="Minimum years of experience (0 = not specified)"
            )
        with col2:
            st.number_input(
                "Max Years Experience",
                min_value=0,
                max_value=20,
                key="config_max_years",
                help="Maximum years of experience (0 = not specified)"
            )

        # Skills (optional)
        st.text_area(
            "Required Skills",
            key="config_skills",
            height=100,
            help="One skill per line. Optional: 'Skill (category, level)' format"
        )

        # Benefit keywords (optional)
        st.text_area(
            "Benefit Keywords",
            key="config_benefit_keywords",
            height=80,
            help="Enter keywords separated by commas or one per line. Only these exact keywords will be used in the benefits section."
        )
        
        # Show calculated temperature (always enabled)
        try:
            from helpers.config_helper import get_job_config_from_session
            from generators.job_generator import explain_temperature
            config = get_job_config_from_session()
            temp = config.temperature
            st.markdown("---")
            st.caption(f"**Calculated Temperature:** {temp:.2f}")
            with st.expander("Temperature Breakdown"):
                st.code(explain_temperature(config))
        except Exception as e:
            pass
        
        # Show style routing preview (Motivkompass)
        try:
            from helpers.config_helper import get_job_config_from_session
            from services.style_router import route_style, explain_style_routing
            config = get_job_config_from_session()
            profile = route_style(config)
            
            # Color emoji map
            color_emoji = {"red": "🔴", "yellow": "🟡", "blue": "🔵", "green": "🟢"}
            primary_emoji = color_emoji.get(profile.primary_color, "⚪")
            
            st.markdown("---")
            st.caption(f"**Style Profile:** {primary_emoji} {profile.primary_color.title()}"
                       + (f" + {color_emoji.get(profile.secondary_color, '')} {profile.secondary_color.title()}"
                          if profile.secondary_color else ""))
            st.caption(f"Mode: {profile.interaction_mode} | Frame: {profile.reference_frame}")
            
            with st.expander("Style Routing Breakdown"):
                st.code(explain_style_routing(config))
        except Exception as e:
            pass
        
        # Display RULER rankings if available
        render_ruler_rankings()


def render_config_expander():
    """Render configuration as an expander in the main content area.

    NOTE: This function uses the SAME session-state keys as
    ``render_config_sidebar``.  Only one of the two should be rendered per
    page — never both — otherwise Streamlit raises DuplicateWidgetID.
    """
    _init_config_defaults()

    with st.expander("⚙️ Generation Settings", expanded=False):
        st.markdown("---")
        col1, col2, col3 = st.columns(3)

        with col1:
            st.selectbox("Language", options=["en", "de"], key="config_language")
            st.selectbox(
                "Tone",
                options=["casual", "neutral", "formal"],
                key="config_formality",
            )

        with col2:
            _ct = [
                "startup", "scaleup", "sme", "corporate", "public_sector",
                "social_sector", "agency", "consulting", "hospitality", "retail",
            ]
            st.selectbox(
                "Company Type",
                options=_ct,
                key="config_company_type",
                format_func=lambda x: {
                    "startup": "Startup",
                    "scaleup": "Scaleup",
                    "sme": "SME / KMU",
                    "corporate": "Corporate",
                    "public_sector": "Public Sector",
                    "social_sector": "Social Sector / Stiftung",
                    "agency": "Agency",
                    "consulting": "Consulting",
                    "hospitality": "Hospitality / Gastronomie",
                    "retail": "Retail / Detailhandel",
                }.get(x, x),
            )
            st.selectbox(
                "Industry",
                options=["generic", "finance", "healthcare", "social_care", "public_it", "ai_startup", "ecommerce", "manufacturing"],
                key="config_industry",
            )

        with col3:
            st.selectbox(
                "Seniority",
                options=["", "intern", "junior", "mid", "senior", "lead", "principal"],
                key="config_seniority_label",
                format_func=lambda x: "Not specified" if x == "" else x.title(),
            )
            col_min, col_max = st.columns(2)
            with col_min:
                st.number_input("Min Years", min_value=0, max_value=20, key="config_min_years")
            with col_max:
                st.number_input("Max Years", min_value=0, max_value=20, key="config_max_years")

