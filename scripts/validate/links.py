# -*- coding: utf-8 -*-

import re
import sys
import random
import json
import os
import time
import yaml
from typing import List, Tuple, Dict, Any, Optional
from pathlib import Path

import requests
from requests.models import Response


# Default configuration values
DEFAULT_CONFIG = {
    'cache': {
        'ttl': 24 * 60 * 60,  # 24 hours in seconds
        'file': 'link_cache.json'
    },
    'validation': {
        'request_timeout': 10,
        'success_status_codes': [200, 301, 302, 303, 307, 308],
        'max_retries': 3,
        'retry_delay': 2,
        'user_agents': [
            'Mozilla/5.0 (Windows NT 6.2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/28.0.1467.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/605.1.15 (KHTML, like Gecko)',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.132 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36',
        ]
    }
}


def load_config() -> Dict[str, Any]:
    """Load configuration from YAML file, falling back to defaults."""
    config = DEFAULT_CONFIG.copy()
    
    # Try to load from multiple possible locations
    config_paths = [
        Path(__file__).parent / "validation_config.yaml",
        Path(__file__).parent.parent / "validation_config.yaml",
        Path.cwd() / "validation_config.yaml",
        Path.home() / ".pulse" / "validation_config.yaml"
    ]
    
    for config_path in config_paths:
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    user_config = yaml.safe_load(f)
                    if user_config:
                        # Deep merge user config with defaults
                        _deep_merge(config, user_config)
                break
            except (yaml.YAMLError, IOError):
                # If config file is corrupted or unreadable, use defaults
                pass
    
    return config


def _deep_merge(base: Dict, update: Dict) -> None:
    """Recursively merge update dict into base dict."""
    for key, value in update.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


# Load configuration at module level
CONFIG = load_config()

# Cache configuration from config
CACHE_FILE = Path(__file__).parent / CONFIG['cache']['file']
CACHE_TTL = CONFIG['cache']['ttl']

# Validation configuration from config
REQUEST_TIMEOUT = CONFIG['validation']['request_timeout']
SUCCESS_STATUS_CODES = CONFIG['validation']['success_status_codes']
MAX_RETRIES = CONFIG['validation']['max_retries']
RETRY_DELAY = CONFIG['validation']['retry_delay']
USER_AGENTS = CONFIG['validation']['user_agents']


class LinkCache:
    """Intelligent caching system for link validation results."""
    
    def __init__(self, cache_file: Path = CACHE_FILE, ttl: int = CACHE_TTL):
        self.cache_file = cache_file
        self.ttl = ttl
        self.cache: Dict[str, Dict[str, Any]] = {}
        self._load_cache()
    
    def _load_cache(self) -> None:
        """Load cache from file if it exists."""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
                # Clean expired entries on load
                self._clean_expired()
        except (json.JSONDecodeError, IOError):
            # If cache file is corrupted or unreadable, start fresh
            self.cache = {}
    
    def _save_cache(self) -> None:
        """Save cache to file."""
        try:
            # Ensure directory exists
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=2)
        except IOError:
            # Silently fail if we can't write cache
            pass
    
    def _clean_expired(self) -> None:
        """Remove expired entries from cache."""
        current_time = time.time()
        expired_keys = []
        
        for url, data in self.cache.items():
            if current_time - data.get('timestamp', 0) > self.ttl:
                expired_keys.append(url)
        
        for key in expired_keys:
            del self.cache[key]
        
        if expired_keys:
            self._save_cache()
    
    def get(self, url: str) -> Optional[Tuple[bool, str]]:
        """Get cached result for a URL if it exists and is not expired."""
        if url in self.cache:
            data = self.cache[url]
            if time.time() - data.get('timestamp', 0) <= self.ttl:
                return (data['has_error'], data['error_message'])
        return None
    
    def set(self, url: str, has_error: bool, error_message: str) -> None:
        """Cache the result for a URL."""
        self.cache[url] = {
            'has_error': has_error,
            'error_message': error_message,
            'timestamp': time.time()
        }
        self._save_cache()
    
    def invalidate(self, url: str) -> None:
        """Invalidate cache for a specific URL."""
        if url in self.cache:
            del self.cache[url]
            self._save_cache()
    
    def clear(self) -> None:
        """Clear entire cache."""
        self.cache = {}
        self._save_cache()


# Global cache instance
link_cache = LinkCache()


def find_links_in_text(text: str) -> List[str]:
    """Find links in a text and return a list of URLs."""

    link_pattern = re.compile(r'((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:\'\".,<>?«»""'']))')

    raw_links = re.findall(link_pattern, text)

    links = [
        str(raw_link[0]) for raw_link in raw_links
    ]

    return links


def find_links_in_file(filename: str) -> List[str]:
    """Find links in a file and return a list of URLs from text file."""

    with open(filename, mode='r', encoding='utf-8') as file:
        readme = file.read()
        index_section = readme.find('## Index')
        if index_section == -1:
            index_section = 0
        content = readme[index_section:]

    links = find_links_in_text(content)

    return links


def check_duplicate_links(links: List[str]) -> Tuple[bool, List]:
    """Check for duplicated links.

    Returns a tuple with True or False and duplicate list.
    """

    seen = {}
    duplicates = []
    has_duplicate = False

    for link in links:
        link = link.rstrip('/')
        if link not in seen:
            seen[link] = 1
        else:
            if seen[link] == 1:
                duplicates.append(link)

    if duplicates:
        has_duplicate = True

    return (has_duplicate, duplicates)


def fake_user_agent() -> str:
    """Faking user agent as some hosting services block not-whitelisted UA."""
    return random.choice(USER_AGENTS)


def get_host_from_link(link: str) -> str:

    host = link.split('://', 1)[1] if '://' in link else link

    # Remove routes, arguments and anchors
    if '/' in host:
        host = host.split('/', 1)[0]

    elif '?' in host:
        host = host.split('?', 1)[0]

    elif '#' in host:
        host = host.split('#', 1)[0]

    return host


def has_cloudflare_protection(resp: Response) -> bool:
    """Checks if there is any cloudflare protection in the response.

    Cloudflare implements multiple network protections on a given link,
    this script tries to detect if any of them exist in the response from request.

    Common protections have the following HTTP code as a response:
        - 403: When host header is missing or incorrect (and more)
        - 503: When DDOS protection exists

    See more about it at:
        - https://support.cloudflare.com/hc/en-us/articles/115003014512-4xx-Client-Error
        - https://support.cloudflare.com/hc/en-us/articles/115003011431-Troubleshooting-Cloudflare-5XX-errors
        - https://www.cloudflare.com/ddos/
        - https://superuser.com/a/888526

    Discussions in issues and pull requests:
        - https://github.com/pulse/pulse/pull/2409
        - https://github.com/pulse/pulse/issues/2960 
    """

    code = resp.status_code
    server = resp.headers.get('Server') or resp.headers.get('server')
    cloudflare_flags = [
        '403 Forbidden',
        'cloudflare',
        'Cloudflare',
        'Security check',
        'Please Wait... | Cloudflare',
        'We are checking your browser...',
        'Please stand by, while we are checking your browser...',
        'Checking your browser before accessing',
        'This process is automatic.',
        'Your browser will redirect to your requested content shortly.',
        'Please allow up to 5 seconds',
        'DDoS protection by',
        'Ray ID:',
        'Cloudflare Ray ID:',
        '_cf_chl',
        '_cf_chl_opt',
        '__cf_chl_rt_tk',
        'cf-spinner-please-wait',
        'cf-spinner-redirecting'
    ]

    if code in [403, 503] and server == 'cloudflare':
        html = resp.text

        flags_found = [flag in html for flag in cloudflare_flags]
        any_flag_found = any(flags_found)

        if any_flag_found:
            return True

    return False


def check_https_support(link: str) -> Tuple[bool, str]:
    """Check if the API supports HTTPS.
    
    Returns (True, '') if HTTPS is supported or if HTTP redirects to HTTPS.
    Returns (False, error_message) if HTTPS is not supported or fails.
    """
    if link.startswith('https://'):
        return (True, '')
    
    # Try HTTPS version if link is HTTP
    https_link = link.replace('http://', 'https://', 1)
    try:
        resp = requests.head(
            https_link,
            headers={'User-Agent': fake_user_agent()},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )
        
        # Check if we got a successful response or redirect
        if resp.status_code in SUCCESS_STATUS_CODES:
            return (True, '')
        else:
            return (False, f"HTTPS returned status code {resp.status_code}")
            
    except requests.exceptions.RequestException as e:
        return (False, f"HTTPS request failed: {str(e)}")


def check_link(link: str, max_retries: int = MAX_RETRIES) -> Tuple[bool, str]:
    """Check if a link is valid and accessible.
    
    Returns (True, '') if link is accessible.
    Returns (False, error_message) if link is not accessible.
    """
    # Check cache first
    cached_result = link_cache.get(link)
    if cached_result is not None:
        return cached_result
    
    # Try with retries
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                link,
                headers={'User-Agent': fake_user_agent()},
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True
            )
            
            # Check for Cloudflare protection
            if has_cloudflare_protection(resp):
                error_msg = "Cloudflare protection detected"
                link_cache.set(link, True, error_msg)
                return (True, error_msg)  # Consider Cloudflare as accessible but with warning
            
            # Check if status code is successful
            if resp.status_code in SUCCESS_STATUS_CODES:
                link_cache.set(link, False, '')
                return (True, '')
            else:
                error_msg = f"HTTP status code: {resp.status_code}"
                if attempt == max_retries - 1:  # Only cache on last attempt
                    link_cache.set(link, True, error_msg)
                return (True, error_msg)  # Consider non-200 but valid codes as accessible
                
        except requests.exceptions.Timeout:
            error_msg = "Request timeout"
            if attempt == max_retries - 1:
                link_cache.set(link, True, error_msg)
            if attempt < max_retries - 1:
                time.sleep(RETRY_DELAY)
                continue
            return (False, error_msg)
            
        except requests.exceptions.ConnectionError:
            error_msg = "Connection error"
            if attempt == max_retries - 1:
                link_cache.set(link, True, error_msg)
            if attempt < max_retries - 1:
                time.sleep(RETRY_DELAY)
                continue
            return (False, error_msg)
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Request failed: {str(e)}"
            if attempt == max_retries - 1:
                link_cache.set(link, True, error_msg)
            if attempt < max_retries - 1:
                time.sleep(RETRY_DELAY)
                continue
            return (False, error_msg)
    
    # This should not be reached, but just in case
    return (False, "Unknown error")


def validate_links(links: List[str]) -> Dict[str, Tuple[bool, str]]:
    """Validate a list of links and return results."""
    results = {}
    
    for link in links:
        # First check HTTPS support
        https_supported, https_error = check_https_support(link)
        
        if not https_supported:
            results[link] = (False, f"HTTPS not supported: {https_error}")
            continue
        
        # Then check if link is accessible
        accessible, access_error = check_link(link)
        
        if accessible:
            results[link] = (True, access_error)  # access_error might contain warnings
        else:
            results[link] = (False, access_error)
    
    return results


def clear_cache() -> None:
    """Clear the link validation cache."""
    link_cache.clear()


def get_cache_stats() -> Dict[str, Any]:
    """Get statistics about the cache."""
    total_entries = len(link_cache.cache)
    current_time = time.time()
    expired_entries = sum(
        1 for data in link_cache.cache.values()
        if current_time - data.get('timestamp', 0) > link_cache.ttl
    )
    
    return {
        'total_entries': total_entries,
        'valid_entries': total_entries - expired_entries,
        'expired_entries': expired_entries,
        'cache_file': str(link_cache.cache_file),
        'cache_ttl_hours': link_cache.ttl / 3600
    }