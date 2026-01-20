# Initialize logging first, before other imports
from logging_config import setup_logging, get_logger

# Initialize logging
setup_logging()
logger = get_logger(__name__)

logger.info("Starting JD Writer MAS application")

# Initialize Langfuse tracing (standard when API keys are configured)
from config import LANGFUSE_ENABLED, LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY
if LANGFUSE_ENABLED:
    from tracing.langfuse_tracing import get_langfuse_callbacks
    callbacks = get_langfuse_callbacks()
    if callbacks:
        logger.info("Langfuse tracing initialized and ready (standard feature)")
    else:
        logger.error(
            "Langfuse keys are configured but tracing initialization failed. "
            "Please check your LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY."
        )
elif LANGFUSE_SECRET_KEY or LANGFUSE_PUBLIC_KEY:
    # Partial configuration detected
    logger.warning(
        "Langfuse keys partially configured. Both LANGFUSE_SECRET_KEY and "
        "LANGFUSE_PUBLIC_KEY are required for tracing. Tracing disabled."
    )
else:
    logger.info("Langfuse tracing not configured (API keys not set in .env)")

import streamlit as st
import config
from ui.layout import (
    render_header,
    render_title,
    render_navigation,
    render_content_editor,
    render_preview,
)
from ui.config_panel import render_config_sidebar
from ui.feedback_panel import render_feedback_buttons, render_history_panel
from ui.company_scraper_panel import render_company_scraper_panel
from database.models import get_db_manager

# Page configuration
st.set_page_config(page_title="Job Editor with Agent", layout="wide")

# Password protection (MVP testing safeguard)
# Check authentication FIRST, before any other UI rendering
if config.STREAMLIT_PASSWORD:
    # Initialize authenticated state if not present
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    # Only show login screen if not authenticated
    if not st.session_state.authenticated:
        st.title("🔒 Access Required")

        # Username is optional; require it only if set in env
        username_input = None
        if config.STREAMLIT_USERNAME:
            username_input = st.text_input("Username:")

        password_input = st.text_input("Password:", type="password")
        if st.button("Login"):
            username_ok = (not config.STREAMLIT_USERNAME) or (username_input == config.STREAMLIT_USERNAME)
            password_ok = password_input == config.STREAMLIT_PASSWORD

            if username_ok and password_ok:
                st.session_state.authenticated = True
                st.rerun()  # Refresh to show authenticated view
            else:
                if config.STREAMLIT_USERNAME and not username_ok:
                    st.error("Incorrect username. Please try again.")
                else:
                    st.error("Incorrect password. Please try again.")
        
        # Stop execution if not authenticated (prevents rest of app from rendering)
        st.stop()

# Initialize session state
# Use setdefault to only set if not already present (preserves user input)
for k, v in config.DEFAULT_JOB_DATA.items():
    if k not in st.session_state:
        st.session_state[k] = v

if "messages" not in st.session_state:
    st.session_state.messages = []

# Initialize advanced generation settings (always enabled with blackboard architecture)
st.session_state.use_advanced_generation = True

# Initialize user ID (in production, this would come from authentication)
if "user_id" not in st.session_state:
    st.session_state.user_id = "default"

# Initialize database
db = get_db_manager()

# Custom CSS and JavaScript for button, checkbox, and slider colors
st.markdown("""
    <style>
        /* Style the Generate Full Job Description button */
        div[data-testid="stButton"] > button[kind="primary"] {
            background-color: rgb(243, 151, 41) !important;
            border-color: rgb(243, 151, 41) !important;
            color: white !important;
        }
        div[data-testid="stButton"] > button[kind="primary"]:hover {
            background-color: rgb(220, 135, 35) !important;
            border-color: rgb(220, 135, 35) !important;
        }
        
        /* Style RULER checkbox - label text */
        div[data-testid="stCheckbox"] label {
            color: rgb(243, 151, 41) !important;
            font-weight: 500;
        }
    </style>
    
    <script>
        // Function to apply custom colors
        function applyCustomColors() {
            const orangeColor = 'rgb(243, 151, 41)';
            
            // Style ALL checkboxes - find all checkbox containers
            document.querySelectorAll('div[data-baseweb="checkbox"]').forEach(checkbox => {
                const input = checkbox.querySelector('input[type="checkbox"]');
                // Find the visual indicator div (usually the first child div after the input)
                const allDivs = checkbox.querySelectorAll('div');
                allDivs.forEach(div => {
                    // Check if this div is the checkbox indicator (has specific styling)
                    const style = window.getComputedStyle(div);
                    if (style.width && style.height && (style.width === style.height || style.borderRadius)) {
                        if (input && input.checked) {
                            div.style.backgroundColor = orangeColor;
                            div.style.borderColor = orangeColor;
                        }
                    }
                });
            });
            
            // Style ALL sliders - comprehensive approach
            document.querySelectorAll('div[data-baseweb="slider"]').forEach(slider => {
                // Find all child divs that might be the track or thumb
                const allElements = slider.querySelectorAll('div, [role="slider"]');
                allElements.forEach(el => {
                    const style = window.getComputedStyle(el);
                    // Check if it's a track fill (has background color and width)
                    if (style.backgroundColor && style.backgroundColor !== 'rgba(0, 0, 0, 0)' && 
                        style.width && parseFloat(style.width) > 0) {
                        el.style.backgroundColor = orangeColor;
                    }
                    // Check if it's a thumb (small square/circle, has transform)
                    if ((style.width === style.height || style.borderRadius) && 
                        (style.transform || style.left || style.right)) {
                        el.style.backgroundColor = orangeColor;
                        el.style.borderColor = orangeColor;
                    }
                });
                
                // Also try to find elements by their computed styles
                const trackFill = slider.querySelector('div[style*="background"]');
                if (trackFill) {
                    trackFill.style.backgroundColor = orangeColor;
                }
                
                const thumb = slider.querySelector('[role="slider"]');
                if (thumb) {
                    thumb.style.backgroundColor = orangeColor;
                    thumb.style.borderColor = orangeColor;
                }
            });
        }
        
        // Apply immediately
        applyCustomColors();
        
        // Apply on page load
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', applyCustomColors);
        } else {
            applyCustomColors();
        }
        
        // Apply after Streamlit updates (using MutationObserver with more aggressive watching)
        const observer = new MutationObserver(function(mutations) {
            applyCustomColors();
        });
        observer.observe(document.body, { 
            childList: true, 
            subtree: true,
            attributes: true,
            attributeFilter: ['style', 'class']
        });
        
        // Also apply on various events
        window.addEventListener('load', applyCustomColors);
        
        // Use Streamlit's custom event if available
        window.addEventListener('streamlit:render', applyCustomColors);
        
        // Periodic check as fallback
        setInterval(applyCustomColors, 500);
    </script>
""", unsafe_allow_html=True)

# Render configuration sidebar
render_config_sidebar()

# Render company scraper panel in sidebar
render_company_scraper_panel()

# Render history panel in sidebar
render_history_panel()

# Render UI components
render_header()
render_title()

# Navigation
render_navigation()

st.markdown("---")

# Main content
left, right = st.columns([0.48, 0.52])
with left:
    render_content_editor()
with right:
    render_preview()
    
    # Add feedback buttons below preview
    job_title = st.session_state.get("job_headline", "")
    if job_title:
        job_dict = {k: st.session_state.get(k, "") for k in config.DEFAULT_JOB_DATA.keys()}
        render_feedback_buttons(job_title, job_dict)
