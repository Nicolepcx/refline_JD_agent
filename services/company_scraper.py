"""
Company scraping service that manages scraping configuration and execution.
Handles scraping intervals, URL management, and integration with vector store.
"""
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from services.scraping_service import scrape_urls_sync, extract_company_name_from_url
from services.vector_store import get_vector_store_manager


class CompanyScraperConfig:
    """Configuration for company scraping."""
    
    def __init__(
        self,
        company_name: str,
        urls: List[str],
        scrape_interval_days: int = 7,  # Default: weekly
        enabled: bool = True,
        last_scraped: Optional[str] = None
    ):
        self.company_name = company_name
        self.urls = urls
        self.scrape_interval_days = scrape_interval_days
        self.enabled = enabled
        self.last_scraped = last_scraped or datetime.now(timezone.utc).isoformat()
    
    def should_scrape(self) -> bool:
        """Check if scraping is due based on interval."""
        if not self.enabled:
            return False
        
        try:
            last_date = datetime.fromisoformat(self.last_scraped.replace('Z', '+00:00'))
            next_scrape = last_date + timedelta(days=self.scrape_interval_days)
            return datetime.now(timezone.utc) >= next_scrape
        except Exception:
            # If parsing fails, assume we should scrape
            return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "company_name": self.company_name,
            "urls": self.urls,
            "scrape_interval_days": self.scrape_interval_days,
            "enabled": self.enabled,
            "last_scraped": self.last_scraped
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompanyScraperConfig":
        """Create from dictionary."""
        return cls(
            company_name=data["company_name"],
            urls=data.get("urls", []),
            scrape_interval_days=data.get("scrape_interval_days", 7),
            enabled=data.get("enabled", True),
            last_scraped=data.get("last_scraped")
        )


class CompanyScraperManager:
    """Manages company scraping configurations and execution."""
    
    def __init__(self, config_file: str = "company_scraper_config.json"):
        self.config_file = Path(config_file)
        self.configs: Dict[str, CompanyScraperConfig] = {}
        self.vector_store = get_vector_store_manager()
        self._load_configs()
    
    def _load_configs(self):
        """Load scraping configurations from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.configs = {
                        name: CompanyScraperConfig.from_dict(config_data)
                        for name, config_data in data.items()
                    }
            except Exception as e:
                logger.warning(f"Error loading scraper configs: {e}", exc_info=True)
                self.configs = {}
        else:
            self.configs = {}
    
    def _save_configs(self):
        """Save scraping configurations to file."""
        try:
            data = {
                name: config.to_dict()
                for name, config in self.configs.items()
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Error saving scraper configs: {e}", exc_info=True)
    
    def add_or_update_company(
        self,
        company_name: str,
        urls: List[str],
        scrape_interval_days: int = 7,
        enabled: bool = True
    ):
        """Add or update company scraping configuration."""
        config = CompanyScraperConfig(
            company_name=company_name,
            urls=urls,
            scrape_interval_days=scrape_interval_days,
            enabled=enabled
        )
        self.configs[company_name] = config
        self._save_configs()
    
    def get_company_config(self, company_name: str) -> Optional[CompanyScraperConfig]:
        """Get configuration for a company."""
        return self.configs.get(company_name)
    
    def get_all_companies(self) -> List[str]:
        """Get list of all configured company names."""
        return list(self.configs.keys())
    
    def scrape_company(
        self,
        company_name: str,
        force: bool = False
    ) -> Optional[str]:
        """
        Scrape content for a company and store in vector DB.
        
        Args:
            company_name: Name of the company
            force: If True, scrape even if not due
            
        Returns:
            Scraped text content (combined) or None if failed
        """
        config = self.configs.get(company_name)
        if not config:
            return None
        
        if not force and not config.should_scrape():
            return None
        
        # Scrape URLs
        content_dict = scrape_urls_sync(config.urls)
        
        if not content_dict:
            return None
        
        # Combine all scraped content
        combined_text = "\n\n".join(content_dict.values())
        
        # Store in vector DB
        metadata = {
            "scrape_interval_days": config.scrape_interval_days,
            "urls": config.urls
        }
        
        success = self.vector_store.add_company_content(
            company_name=company_name,
            urls=config.urls,
            content_dict=content_dict,
            metadata=metadata
        )
        
        if success:
            # Update last scraped timestamp
            config.last_scraped = datetime.now(timezone.utc).isoformat()
            self._save_configs()
        
        return combined_text if success else None
    
    def get_company_content(
        self,
        company_name: str,
        query: Optional[str] = None,
        k: int = 5
    ) -> str:
        """
        Get company content from vector store.
        
        Args:
            company_name: Name of the company
            query: Optional search query (if None, returns general content)
            k: Number of results to retrieve
            
        Returns:
            Combined text content
        """
        if not self.vector_store.is_available():
            return ""
        
        if query:
            results = self.vector_store.search_company_content(company_name, query, k=k)
        else:
            results = self.vector_store.get_company_content(company_name, limit=k)
        
        if not results:
            return ""
        
        # Combine results
        content_parts = [result["content"] for result in results]
        return "\n\n".join(content_parts)
    
    def scrape_company_from_urls(
        self,
        urls: List[str],
        company_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Scrape company content from URLs without storing in config.
        Useful for one-time scraping.
        
        Args:
            urls: List of URLs to scrape
            company_name: Optional company name (auto-detected from URL if not provided)
            
        Returns:
            Combined scraped text or None
        """
        if not urls:
            return None
        
        # Auto-detect company name from first URL if not provided
        if not company_name:
            company_name = extract_company_name_from_url(urls[0])
        
        # Scrape URLs
        content_dict = scrape_urls_sync(urls)
        
        if not content_dict:
            return None
        
        # Combine content
        combined_text = "\n\n".join(content_dict.values())
        
        # Optionally store in vector DB (one-time, not in config)
        if self.vector_store.is_available():
            self.vector_store.add_company_content(
                company_name=company_name,
                urls=urls,
                content_dict=content_dict,
                metadata={"one_time_scrape": True}
            )
        
        return combined_text


# Global instance
_scraper_manager: Optional[CompanyScraperManager] = None


def get_scraper_manager() -> CompanyScraperManager:
    """Get global scraper manager instance."""
    global _scraper_manager
    if _scraper_manager is None:
        _scraper_manager = CompanyScraperManager()
    return _scraper_manager
