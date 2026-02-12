"""
UI components for company scraping configuration.
"""
import streamlit as st
from services.company_scraper import get_scraper_manager
from services.scraping_service import extract_company_name_from_url


def render_company_scraper_panel():
    """Render company scraping configuration panel in sidebar."""
    # Initialise defaults once (avoids mutating state every render cycle)
    st.session_state.setdefault("scraping_enabled", False)
    for i in range(3):
        st.session_state.setdefault(f"company_url_{i}", "")

    with st.sidebar:
        st.markdown("---")
        st.header("🏢 Company Scraping")
        
        # key-only — value managed by session state
        scraping_enabled = st.checkbox(
            "Enable Company Scraping",
            key="scraping_enabled",
            help="Scrape company websites to enhance job descriptions with company-specific information"
        )
        
        if scraping_enabled:
            st.caption("Enter up to 3 company URLs to scrape")
            
            # URL inputs (1-3 URLs)
            urls = []
            for i in range(3):
                url_key = f"company_url_{i}"
                url = st.text_input(
                    f"Company URL {i+1}",
                    key=url_key,
                    placeholder="https://example.com/about"
                )
                if url:
                    urls.append(url)
            
            if urls:
                # Extract company name from first URL
                company_name = extract_company_name_from_url(urls[0])
                
                # Scraping interval
                interval_days = st.selectbox(
                    "Scraping Interval",
                    options=[1, 7, 14, 30, 90],
                    index=1,  # Default: 7 days (weekly)
                    format_func=lambda x: {
                        1: "Daily",
                        7: "Weekly",
                        14: "Bi-weekly",
                        30: "Monthly",
                        90: "Quarterly"
                    }.get(x, f"{x} days"),
                    key="scraping_interval",
                    help="How often to re-scrape the company websites"
                )
                
                # Company name override
                company_name_override = st.text_input(
                    "Company Name (optional)",
                    value=company_name,
                    key="company_name_override",
                    help="Override auto-detected company name"
                )
                
                if company_name_override:
                    company_name = company_name_override
                
                # Save configuration button
                if st.button("💾 Save Scraping Config", key="save_scraping_config"):
                    try:
                        scraper_manager = get_scraper_manager()
                        scraper_manager.add_or_update_company(
                            company_name=company_name,
                            urls=urls,
                            scrape_interval_days=interval_days,
                            enabled=True
                        )
                        st.success(f"✅ Saved configuration for {company_name}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error saving configuration: {e}")
                
                # Manual scrape button
                if st.button("🔄 Scrape Now", key="manual_scrape"):
                    with st.spinner(f"Scraping {company_name}..."):
                        try:
                            scraper_manager = get_scraper_manager()
                            content = scraper_manager.scrape_company_from_urls(
                                urls=urls,
                                company_name=company_name
                            )
                            if content:
                                st.success(f"✅ Scraped {len(content)} characters from {len(urls)} URL(s)")
                                # Store in session state for use in generation
                                st.session_state.company_urls = urls
                                st.session_state.company_name = company_name
                            else:
                                st.warning("⚠️ Scraping completed but no content retrieved")
                        except Exception as e:
                            st.error(f"Error scraping: {e}")
            
            # Show saved configurations
            st.markdown("---")
            st.subheader("📋 Saved Configurations")
            try:
                scraper_manager = get_scraper_manager()
                companies = scraper_manager.get_all_companies()
                
                if companies:
                    for company_name in companies:
                        config = scraper_manager.get_company_config(company_name)
                        if config:
                            with st.expander(f"🏢 {company_name}", expanded=False):
                                st.write(f"**URLs:** {len(config.urls)}")
                                for url in config.urls:
                                    st.caption(f"  • {url}")
                                st.write(f"**Interval:** Every {config.scrape_interval_days} days")
                                st.write(f"**Last Scraped:** {config.last_scraped[:10] if config.last_scraped else 'Never'}")
                                
                                col1, col2 = st.columns(2)
                                with col1:
                                    if st.button("🔄 Scrape Now", key=f"scrape_{company_name}"):
                                        with st.spinner(f"Scraping {company_name}..."):
                                            content = scraper_manager.scrape_company(
                                                company_name,
                                                force=True
                                            )
                                            if content:
                                                st.success("✅ Scraping completed")
                                                st.rerun()
                                with col2:
                                    if st.button("🗑️ Delete", key=f"delete_{company_name}"):
                                        # Note: Add delete method to manager if needed
                                        st.info("Delete functionality coming soon")
                else:
                    st.caption("No saved configurations")
            except Exception as e:
                st.error(f"Error loading configurations: {e}")
        else:
            # Clear URLs when scraping is disabled, but only if they had
            # values (avoids pointless state writes that trigger re-runs).
            if st.session_state.get("company_urls"):
                st.session_state["company_urls"] = []
            if st.session_state.get("company_name"):
                st.session_state["company_name"] = None


def get_company_urls_from_session() -> list:
    """Get company URLs from session state."""
    return st.session_state.get("company_urls", [])


def get_company_name_from_session() -> str:
    """Get company name from session state."""
    return st.session_state.get("company_name", "")
