"""Intelligent caching system for link validation results.

This module provides a Cache class that stores URL validation status with timestamps
using file-based JSON storage. It implements time-based cache invalidation and supports
manual cache clearing for improved performance and reduced external API calls.
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Default cache expiration time in seconds (24 hours)
DEFAULT_EXPIRY_SECONDS = 24 * 60 * 60

# Default cache file location
DEFAULT_CACHE_FILE = Path(__file__).parent.parent.parent / "cache" / "validation_cache.json"


class Cache:
    """Intelligent cache for URL validation results.
    
    Stores validation results with timestamps and automatically expires entries
    after a configurable period. Uses JSON file storage for persistence.
    """
    
    def __init__(
        self,
        cache_file: Path = DEFAULT_CACHE_FILE,
        expiry_seconds: int = DEFAULT_EXPIRY_SECONDS,
        auto_create_dir: bool = True
    ):
        """Initialize the cache.
        
        Args:
            cache_file: Path to the JSON cache file
            expiry_seconds: Time in seconds before cache entries expire
            auto_create_dir: Whether to automatically create cache directory if needed
        """
        self.cache_file = Path(cache_file)
        self.expiry_seconds = expiry_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._last_loaded: Optional[float] = None
        
        if auto_create_dir:
            self._ensure_cache_dir()
        
        # Load existing cache on initialization
        self.load()
    
    def _ensure_cache_dir(self) -> None:
        """Create cache directory if it doesn't exist."""
        cache_dir = self.cache_file.parent
        if not cache_dir.exists():
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created cache directory: {cache_dir}")
            except OSError as e:
                logger.error(f"Failed to create cache directory {cache_dir}: {e}")
                raise
    
    def load(self) -> None:
        """Load cache from JSON file.
        
        If the cache file doesn't exist or is invalid, starts with empty cache.
        """
        if not self.cache_file.exists():
            logger.debug(f"Cache file not found: {self.cache_file}")
            self._cache = {}
            return
        
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Validate cache structure
            if not isinstance(data, dict):
                logger.warning("Invalid cache format: expected dictionary")
                self._cache = {}
                return
                
            self._cache = data
            self._last_loaded = time.time()
            logger.debug(f"Loaded cache with {len(self._cache)} entries from {self.cache_file}")
            
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Failed to parse cache file {self.cache_file}: {e}")
            self._cache = {}
        except Exception as e:
            logger.error(f"Unexpected error loading cache: {e}")
            self._cache = {}
    
    def save(self) -> None:
        """Save cache to JSON file.
        
        Creates backup of existing cache file before overwriting.
        """
        self._ensure_cache_dir()
        
        # Create backup if cache file exists
        if self.cache_file.exists():
            backup_file = self.cache_file.with_suffix('.json.bak')
            try:
                backup_file.write_bytes(self.cache_file.read_bytes())
            except Exception as e:
                logger.warning(f"Failed to create cache backup: {e}")
        
        try:
            # Write to temporary file first, then rename for atomic operation
            temp_file = self.cache_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
            
            # Atomic rename
            temp_file.replace(self.cache_file)
            logger.debug(f"Saved cache with {len(self._cache)} entries to {self.cache_file}")
            
        except Exception as e:
            logger.error(f"Failed to save cache to {self.cache_file}: {e}")
            raise
    
    def _is_expired(self, timestamp: float) -> bool:
        """Check if a cache entry is expired.
        
        Args:
            timestamp: Unix timestamp of when entry was cached
            
        Returns:
            True if entry is expired, False otherwise
        """
        return time.time() - timestamp > self.expiry_seconds
    
    def get(self, url: str) -> Optional[Tuple[int, str, float]]:
        """Get cached validation result for a URL.
        
        Args:
            url: URL to look up in cache
            
        Returns:
            Tuple of (status_code, status_text, timestamp) if found and not expired,
            None otherwise
        """
        if url not in self._cache:
            return None
        
        entry = self._cache[url]
        timestamp = entry.get('timestamp', 0)
        
        if self._is_expired(timestamp):
            logger.debug(f"Cache expired for URL: {url}")
            # Remove expired entry
            del self._cache[url]
            return None
        
        return (
            entry.get('status_code'),
            entry.get('status_text', ''),
            timestamp
        )
    
    def set(
        self,
        url: str,
        status_code: int,
        status_text: str = '',
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Cache validation result for a URL.
        
        Args:
            url: URL that was validated
            status_code: HTTP status code or validation result code
            status_text: Description of the validation result
            metadata: Additional metadata to store with the result
        """
        timestamp = time.time()
        
        entry = {
            'status_code': status_code,
            'status_text': status_text,
            'timestamp': timestamp,
            'cached_at': datetime.fromtimestamp(timestamp).isoformat()
        }
        
        if metadata:
            entry['metadata'] = metadata
        
        self._cache[url] = entry
        logger.debug(f"Cached result for URL: {url} (status: {status_code})")
    
    def invalidate(self, url: str) -> bool:
        """Remove a specific URL from cache.
        
        Args:
            url: URL to remove from cache
            
        Returns:
            True if entry was found and removed, False otherwise
        """
        if url in self._cache:
            del self._cache[url]
            logger.debug(f"Invalidated cache for URL: {url}")
            return True
        return False
    
    def clear(self) -> int:
        """Clear all cache entries.
        
        Returns:
            Number of entries cleared
        """
        count = len(self._cache)
        self._cache.clear()
        logger.info(f"Cleared {count} cache entries")
        return count
    
    def cleanup_expired(self) -> int:
        """Remove all expired entries from cache.
        
        Returns:
            Number of expired entries removed
        """
        expired_urls = []
        
        for url, entry in self._cache.items():
            timestamp = entry.get('timestamp', 0)
            if self._is_expired(timestamp):
                expired_urls.append(url)
        
        for url in expired_urls:
            del self._cache[url]
        
        if expired_urls:
            logger.info(f"Cleaned up {len(expired_urls)} expired cache entries")
        
        return len(expired_urls)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        total_entries = len(self._cache)
        now = time.time()
        
        expired_count = 0
        valid_count = 0
        
        for entry in self._cache.values():
            timestamp = entry.get('timestamp', 0)
            if self._is_expired(timestamp):
                expired_count += 1
            else:
                valid_count += 1
        
        return {
            'total_entries': total_entries,
            'valid_entries': valid_count,
            'expired_entries': expired_count,
            'cache_file': str(self.cache_file),
            'expiry_seconds': self.expiry_seconds,
            'last_loaded': self._last_loaded
        }
    
    def __len__(self) -> int:
        """Return number of entries in cache."""
        return len(self._cache)
    
    def __contains__(self, url: str) -> bool:
        """Check if URL is in cache and not expired."""
        return self.get(url) is not None


# Global cache instance for convenience
_global_cache: Optional[Cache] = None


def get_cache(
    cache_file: Optional[Path] = None,
    expiry_seconds: int = DEFAULT_EXPIRY_SECONDS
) -> Cache:
    """Get or create global cache instance.
    
    Args:
        cache_file: Path to cache file (uses default if None)
        expiry_seconds: Cache expiry time in seconds
        
    Returns:
        Global Cache instance
    """
    global _global_cache
    
    if _global_cache is None or (cache_file and _global_cache.cache_file != cache_file):
        _global_cache = Cache(
            cache_file=cache_file or DEFAULT_CACHE_FILE,
            expiry_seconds=expiry_seconds
        )
    
    return _global_cache


def clear_global_cache() -> None:
    """Clear the global cache instance."""
    global _global_cache
    if _global_cache:
        _global_cache.clear()
        _global_cache = None


# Integration with existing validation workflow
def validate_with_cache(
    url: str,
    validator_func,
    cache: Optional[Cache] = None,
    force_refresh: bool = False,
    **validator_kwargs
) -> Tuple[int, str]:
    """Validate a URL using cache when possible.
    
    This function integrates caching with URL validation. It checks the cache first
    and only calls the validator function if the URL is not cached or cache is expired.
    
    Args:
        url: URL to validate
        validator_func: Function that performs actual validation
        cache: Cache instance to use (uses global cache if None)
        force_refresh: If True, bypass cache and force fresh validation
        **validator_kwargs: Additional arguments to pass to validator_func
        
    Returns:
        Tuple of (status_code, status_text)
    """
    if cache is None:
        cache = get_cache()
    
    # Check cache first (unless forcing refresh)
    if not force_refresh:
        cached_result = cache.get(url)
        if cached_result is not None:
            status_code, status_text, _ = cached_result
            logger.debug(f"Using cached result for {url}: {status_code}")
            return status_code, status_text
    
    # Perform fresh validation
    try:
        status_code, status_text = validator_func(url, **validator_kwargs)
        
        # Cache successful validation (or any validation result)
        cache.set(url, status_code, status_text)
        
        # Periodically cleanup expired entries (every 100 cache operations)
        if len(cache) % 100 == 0:
            cache.cleanup_expired()
        
        return status_code, status_text
        
    except Exception as e:
        logger.error(f"Validation failed for {url}: {e}")
        # Cache errors with a special status code (e.g., 0 for connection error)
        error_status = 0
        error_text = f"Validation error: {str(e)}"
        cache.set(url, error_status, error_text)
        return error_status, error_text


# Example usage with existing links.py validation
def integrate_with_links_module():
    """Example of how to integrate cache with existing links.py validation.
    
    This function demonstrates the integration pattern. The actual integration
    would be done in the links.py module.
    """
    # Import would be at top of links.py:
    # from scripts.validate.cache import validate_with_cache, get_cache
    
    # Example validator function (would be actual validation logic)
    def example_validator(url: str, timeout: int = 10) -> Tuple[int, str]:
        """Example validator that makes HTTP request."""
        import requests
        try:
            response = requests.head(url, timeout=timeout, allow_redirects=True)
            return response.status_code, response.reason or "OK"
        except requests.RequestException as e:
            return 0, str(e)
    
    # Usage in validation workflow:
    cache = get_cache()
    
    # Validate with cache
    status_code, status_text = validate_with_cache(
        url="https://example.com",
        validator_func=example_validator,
        cache=cache,
        timeout=5
    )
    
    print(f"URL: https://example.com - Status: {status_code} - {status_text}")
    
    # Save cache after batch of validations
    cache.save()


if __name__ == "__main__":
    # Simple test/demo when run directly
    import sys
    
    logging.basicConfig(level=logging.DEBUG)
    
    # Create test cache
    test_cache = Cache(cache_file=Path("test_cache.json"), expiry_seconds=60)
    
    # Test operations
    test_cache.set("https://example.com", 200, "OK")
    test_cache.set("https://github.com", 200, "OK")
    
    print(f"Cache stats: {test_cache.get_stats()}")
    
    # Test retrieval
    result = test_cache.get("https://example.com")
    if result:
        print(f"Cached result: {result}")
    
    # Test expiration
    test_cache.expiry_seconds = 0  # Force immediate expiration
    result = test_cache.get("https://example.com")
    print(f"After expiration: {result}")
    
    # Cleanup
    test_cache.clear()
    test_cache.cache_file.unlink(missing_ok=True)
    
    print("Cache test completed")