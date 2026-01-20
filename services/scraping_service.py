"""
Website scraping service for company information.
Modular service that can be optionally enabled/disabled.
"""
import asyncio
from typing import List, Optional, Dict
from urllib.parse import urlparse
from datetime import datetime, timezone
from logging_config import get_logger

logger = get_logger(__name__)

try:
    from langchain_community.document_loaders import WebBaseLoader
    from bs4 import BeautifulSoup
    SCRAPING_AVAILABLE = True
except ImportError:
    SCRAPING_AVAILABLE = False
    logger.warning("Scraping dependencies not available. Install beautifulsoup4 and langchain_community.")


def extract_company_name_from_url(url: str) -> str:
    """Extract company name from URL domain."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        # Remove www. prefix
        domain = domain.replace("www.", "")
        # Get the main domain name (e.g., 'refline.io' -> 'refline')
        parts = domain.split(".")
        if len(parts) >= 2:
            return parts[0]
        return domain.split("/")[0] if "/" in domain else domain
    except Exception:
        return "unknown_company"


async def scrape_urls(urls: List[str], timeout: int = 30) -> Dict[str, str]:
    """
    Scrape content from multiple URLs asynchronously.
    
    Args:
        urls: List of URLs to scrape
        timeout: Request timeout in seconds
        
    Returns:
        Dictionary mapping URL to scraped text content
    """
    if not SCRAPING_AVAILABLE:
        return {}
    
    results = {}
    
    async def scrape_single_url(url: str):
        """Scrape a single URL."""
        try:
            loader = WebBaseLoader(url)
            # Use async method if available, otherwise fallback to sync
            if hasattr(loader, "aload"):
                docs = await loader.aload()
            else:
                # Run sync load in thread pool
                loop = asyncio.get_event_loop()
                docs = await loop.run_in_executor(None, loader.load)
            
            if docs:
                # Combine all document pages into one text
                text_content = "\n\n".join([doc.page_content for doc in docs])
                # Clean up the text (remove excessive whitespace)
                text_content = " ".join(text_content.split())
                return url, text_content
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}", exc_info=True)
            return url, None
    
    # Scrape all URLs concurrently
    tasks = [scrape_single_url(url) for url in urls]
    scraped_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for result in scraped_results:
        if isinstance(result, Exception):
            continue
        url, content = result
        if content:
            results[url] = content
    
    return results


def scrape_urls_sync(urls: List[str]) -> Dict[str, str]:
    """
    Synchronous wrapper for scraping URLs.
    Use this when you can't use async context.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is already running, create new event loop in thread
            import concurrent.futures
            import threading
            
            result = None
            exception = None
            
            def run_in_thread():
                nonlocal result, exception
                try:
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    result = new_loop.run_until_complete(scrape_urls(urls))
                    new_loop.close()
                except Exception as e:
                    exception = e
            
            thread = threading.Thread(target=run_in_thread)
            thread.start()
            thread.join()
            
            if exception:
                raise exception
            return result or {}
        else:
            return loop.run_until_complete(scrape_urls(urls))
    except RuntimeError:
        # No event loop, create one
        return asyncio.run(scrape_urls(urls))
