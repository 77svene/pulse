#!/usr/bin/env python3
"""
Extended API Validation Suite for pulse
Validates API endpoints for response codes, content types, HTTPS support, and basic functionality
"""

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException, Timeout, ConnectionError
from urllib3.util.retry import Retry

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from validate.cache import Cache
from validate.format import Formatter

# Constants
DEFAULT_TIMEOUT = 10
MAX_RETRIES = 2
BACKOFF_FACTOR = 0.5
USER_AGENT = "pulse-validator/1.0 (https://github.com/pulse/pulse)"
CACHE_TTL = 3600  # 1 hour cache

class ValidationStatus(Enum):
    """Status of API validation"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    AUTH_REQUIRED = "auth_required"
    INVALID_SSL = "invalid_ssl"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"

@dataclass
class ValidationRule:
    """Validation rule configuration"""
    name: str
    description: str
    required: bool = True
    enabled: bool = True

@dataclass
class ValidationResult:
    """Result of API validation"""
    url: str
    status: ValidationStatus
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    response_time: Optional[float] = None
    https_supported: bool = False
    cors_supported: Optional[bool] = None
    auth_required: Optional[bool] = None
    rate_limit_detected: bool = False
    error_message: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    validated_at: str = None
    
    def __post_init__(self):
        if self.validated_at is None:
            self.validated_at = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        result = asdict(self)
        result['status'] = self.status.value
        return result
    
    def is_valid(self) -> bool:
        """Check if API passes basic validation"""
        return (
            self.status == ValidationStatus.ACTIVE and
            self.https_supported and
            (self.status_code is None or 200 <= self.status_code < 400)
        )

class APIValidator:
    """Extended API validation suite"""
    
    def __init__(self, cache_dir: Optional[str] = None, max_workers: int = 10):
        """
        Initialize API validator
        
        Args:
            cache_dir: Directory for caching results
            max_workers: Maximum concurrent validation threads
        """
        self.cache = Cache(cache_dir or Path(__file__).parent / ".cache")
        self.formatter = Formatter()
        self.max_workers = max_workers
        self.session = self._create_session()
        
        # Define validation rules
        self.rules = {
            'https': ValidationRule('https', 'HTTPS support', required=True),
            'status_code': ValidationRule('status_code', 'Valid HTTP status code', required=True),
            'content_type': ValidationRule('content_type', 'Valid content type', required=False),
            'response_time': ValidationRule('response_time', 'Response within timeout', required=True),
            'cors': ValidationRule('cors', 'CORS headers present', required=False),
        }
        
        # Common API content types
        self.valid_content_types = {
            'application/json',
            'application/xml',
            'text/xml',
            'text/plain',
            'text/html',
            'application/x-www-form-urlencoded',
            'multipart/form-data',
        }
        
        # Rate limit headers to check
        self.rate_limit_headers = [
            'x-ratelimit-limit',
            'x-ratelimit-remaining',
            'x-rate-limit-limit',
            'x-rate-limit-remaining',
            'ratelimit-limit',
            'ratelimit-remaining',
            'retry-after',
        ]
        
        # Authentication headers
        self.auth_headers = [
            'www-authenticate',
            'x-api-key',
            'authorization',
        ]
    
    def _create_session(self) -> requests.Session:
        """Create requests session with retry logic"""
        session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=MAX_RETRIES,
            backoff_factor=BACKOFF_FACTOR,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': 'application/json, application/xml, text/xml, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        
        return session
    
    def validate_url(self, url: str, check_cors: bool = True) -> ValidationResult:
        """
        Validate a single API endpoint
        
        Args:
            url: API endpoint URL
            check_cors: Whether to check CORS headers
            
        Returns:
            ValidationResult with validation details
        """
        # Check cache first
        cache_key = f"api_validation_{hash(url)}"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            return ValidationResult(**cached_result)
        
        parsed_url = urlparse(url)
        https_supported = parsed_url.scheme == 'https'
        
        # Initial result
        result = ValidationResult(
            url=url,
            status=ValidationStatus.UNKNOWN,
            https_supported=https_supported
        )
        
        try:
            # Start timing
            start_time = time.time()
            
            # Make HEAD request first (lighter)
            response = self.session.head(
                url,
                timeout=DEFAULT_TIMEOUT,
                allow_redirects=True,
                verify=True
            )
            
            # If HEAD fails or returns 405, try GET
            if response.status_code == 405 or response.status_code >= 400:
                response = self.session.get(
                    url,
                    timeout=DEFAULT_TIMEOUT,
                    allow_redirects=True,
                    verify=True,
                    stream=True  # Don't download full body
                )
                # Close the response to avoid downloading full content
                response.close()
            
            # Calculate response time
            response_time = time.time() - start_time
            
            # Update result
            result.status_code = response.status_code
            result.response_time = response_time
            result.headers = dict(response.headers)
            
            # Check HTTPS support
            result.https_supported = self._check_https_support(url)
            
            # Check content type
            content_type = response.headers.get('content-type', '').split(';')[0].strip()
            result.content_type = content_type if content_type else None
            
            # Check CORS support
            if check_cors:
                result.cors_supported = self._check_cors_support(response.headers)
            
            # Check authentication requirements
            result.auth_required = self._check_auth_required(response.headers, response.status_code)
            
            # Check rate limiting
            result.rate_limit_detected = self._check_rate_limiting(response.headers)
            
            # Determine overall status
            result.status = self._determine_status(response, response_time, https_supported)
            
            # Cache successful result
            if result.status == ValidationStatus.ACTIVE:
                self.cache.set(cache_key, result.to_dict(), ttl=CACHE_TTL)
            
            return result
            
        except Timeout:
            result.status = ValidationStatus.TIMEOUT
            result.error_message = f"Request timed out after {DEFAULT_TIMEOUT} seconds"
            return result
            
        except ConnectionError as e:
            result.status = ValidationStatus.INACTIVE
            result.error_message = f"Connection error: {str(e)}"
            return result
            
        except RequestException as e:
            result.status = ValidationStatus.ERROR
            result.error_message = f"Request failed: {str(e)}"
            return result
            
        except Exception as e:
            result.status = ValidationStatus.ERROR
            result.error_message = f"Unexpected error: {str(e)}"
            return result
    
    def _check_https_support(self, url: str) -> bool:
        """Check if API supports HTTPS"""
        parsed = urlparse(url)
        if parsed.scheme == 'https':
            return True
        
        # Try HTTPS version if HTTP
        if parsed.scheme == 'http':
            https_url = url.replace('http://', 'https://', 1)
            try:
                response = self.session.head(
                    https_url,
                    timeout=5,
                    allow_redirects=True,
                    verify=True
                )
                return response.status_code < 400
            except:
                return False
        
        return False
    
    def _check_cors_support(self, headers: Dict[str, str]) -> Optional[bool]:
        """Check if API supports CORS"""
        cors_headers = [
            'access-control-allow-origin',
            'access-control-allow-methods',
            'access-control-allow-headers',
        ]
        
        # Check for any CORS header
        for header in cors_headers:
            if header in headers:
                return True
        
        # If no CORS headers found, it might still support CORS but not advertise it
        return None
    
    def _check_auth_required(self, headers: Dict[str, str], status_code: int) -> Optional[bool]:
        """Check if API requires authentication"""
        # Check for 401/403 status codes
        if status_code in (401, 403):
            return True
        
        # Check for auth headers in response
        for header in self.auth_headers:
            if header in headers:
                return True
        
        return False
    
    def _check_rate_limiting(self, headers: Dict[str, str]) -> bool:
        """Check if API has rate limiting"""
        for header in self.rate_limit_headers:
            if header in headers:
                return True
        return False
    
    def _determine_status(self, response: requests.Response, response_time: float, https_supported: bool) -> ValidationStatus:
        """Determine overall validation status"""
        if response.status_code == 429:
            return ValidationStatus.RATE_LIMITED
        
        if response.status_code in (401, 403):
            return ValidationStatus.AUTH_REQUIRED
        
        if response.status_code >= 500:
            return ValidationStatus.INACTIVE
        
        if response.status_code >= 400:
            return ValidationStatus.ERROR
        
        if response_time > DEFAULT_TIMEOUT:
            return ValidationStatus.TIMEOUT
        
        if not https_supported:
            return ValidationStatus.INVALID_SSL
        
        if 200 <= response.status_code < 300:
            return ValidationStatus.ACTIVE
        
        if 300 <= response.status_code < 400:
            # Redirects are generally okay
            return ValidationStatus.ACTIVE
        
        return ValidationStatus.UNKNOWN
    
    def validate_apis(self, urls: List[str], check_cors: bool = True) -> List[ValidationResult]:
        """
        Validate multiple API endpoints concurrently
        
        Args:
            urls: List of API URLs to validate
            check_cors: Whether to check CORS headers
            
        Returns:
            List of ValidationResult objects
        """
        results = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all validation tasks
            future_to_url = {
                executor.submit(self.validate_url, url, check_cors): url 
                for url in urls
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    # Create error result for failed validation
                    error_result = ValidationResult(
                        url=url,
                        status=ValidationStatus.ERROR,
                        error_message=f"Validation failed: {str(e)}"
                    )
                    results.append(error_result)
        
        # Sort results by URL for consistent output
        results.sort(key=lambda x: x.url)
        return results
    
    def validate_from_readme(self, readme_path: str = "README.md") -> List[ValidationResult]:
        """
        Extract and validate APIs from README file
        
        Args:
            readme_path: Path to README.md file
            
        Returns:
            List of ValidationResult objects
        """
        urls = self._extract_api_urls_from_readme(readme_path)
        return self.validate_apis(urls)
    
    def _extract_api_urls_from_readme(self, readme_path: str) -> List[str]:
        """Extract API URLs from README markdown table"""
        urls = []
        api_pattern = re.compile(r'\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|')
        
        try:
            with open(readme_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Find all API links in markdown table format
            matches = api_pattern.findall(content)
            for name, url in matches:
                if url.startswith('http'):
                    urls.append(url)
                    
        except FileNotFoundError:
            print(f"Warning: README file not found at {readme_path}")
        
        return urls
    
    def generate_report(self, results: List[ValidationResult], format: str = 'text') -> str:
        """
        Generate validation report
        
        Args:
            results: List of validation results
            format: Output format ('text', 'json', 'html')
            
        Returns:
            Formatted report string
        """
        if format == 'json':
            return self._generate_json_report(results)
        elif format == 'html':
            return self._generate_html_report(results)
        else:
            return self._generate_text_report(results)
    
    def _generate_text_report(self, results: List[ValidationResult]) -> str:
        """Generate plain text report"""
        lines = []
        lines.append("=" * 80)
        lines.append("API VALIDATION REPORT")
        lines.append(f"Generated: {datetime.utcnow().isoformat()}")
        lines.append(f"Total APIs validated: {len(results)}")
        lines.append("=" * 80)
        
        # Summary statistics
        status_counts = {}
        for result in results:
            status_counts[result.status] = status_counts.get(result.status, 0) + 1
        
        lines.append("\nSUMMARY:")
        for status, count in status_counts.items():
            lines.append(f"  {status.value}: {count} ({count/len(results)*100:.1f}%)")
        
        # Detailed results
        lines.append("\nDETAILED RESULTS:")
        lines.append("-" * 80)
        
        for result in results:
            lines.append(f"\nURL: {result.url}")
            lines.append(f"Status: {result.status.value}")
            
            if result.status_code:
                lines.append(f"HTTP Status: {result.status_code}")
            if result.content_type:
                lines.append(f"Content-Type: {result.content_type}")
            if result.response_time:
                lines.append(f"Response Time: {result.response_time:.2f}s")
            if result.https_supported is not None:
                lines.append(f"HTTPS: {'✓' if result.https_supported else '✗'}")
            if result.cors_supported is not None:
                lines.append(f"CORS: {'✓' if result.cors_supported else '✗'}")
            if result.auth_required is not None:
                lines.append(f"Auth Required: {'✓' if result.auth_required else '✗'}")
            if result.rate_limit_detected:
                lines.append("Rate Limiting: ✓")
            if result.error_message:
                lines.append(f"Error: {result.error_message}")
        
        return '\n'.join(lines)
    
    def _generate_json_report(self, results: List[ValidationResult]) -> str:
        """Generate JSON report"""
        report = {
            'generated_at': datetime.utcnow().isoformat(),
            'total_apis': len(results),
            'summary': {},
            'results': [result.to_dict() for result in results]
        }
        
        # Add summary
        for result in results:
            status = result.status.value
            report['summary'][status] = report['summary'].get(status, 0) + 1
        
        return json.dumps(report, indent=2)
    
    def _generate_html_report(self, results: List[ValidationResult]) -> str:
        """Generate HTML report"""
        html = []
        html.append("""
<!DOCTYPE html>
<html>
<head>
    <title>API Validation Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .summary { background: #f5f5f5; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
        .result { border: 1px solid #ddd; padding: 15px; margin-bottom: 10px; border-radius: 5px; }
        .active { border-left: 5px solid #4CAF50; }
        .inactive { border-left: 5px solid #f44336; }
        .error { border-left: 5px solid #ff9800; }
        .status { font-weight: bold; }
        .url { color: #2196F3; text-decoration: none; }
        .url:hover { text-decoration: underline; }
        .metric { display: inline-block; margin-right: 20px; }
        .check { color: #4CAF50; }
        .cross { color: #f44336; }
    </style>
</head>
<body>
""")
        
        html.append(f"<h1>API Validation Report</h1>")
        html.append(f"<p>Generated: {datetime.utcnow().isoformat()}</p>")
        html.append(f"<p>Total APIs validated: {len(results)}</p>")
        
        # Summary
        html.append('<div class="summary">')
        html.append('<h2>Summary</h2>')
        status_counts = {}
        for result in results:
            status_counts[result.status] = status_counts.get(result.status, 0) + 1
        
        for status, count in status_counts.items():
            percentage = count / len(results) * 100
            html.append(f'<div class="metric"><strong>{status.value}:</strong> {count} ({percentage:.1f}%)</div>')
        html.append('</div>')
        
        # Results
        html.append('<h2>Detailed Results</h2>')
        for result in results:
            status_class = result.status.value.lower().replace(' ', '-')
            html.append(f'<div class="result {status_class}">')
            html.append(f'<h3><a class="url" href="{result.url}" target="_blank">{result.url}</a></h3>')
            html.append(f'<p class="status">Status: {result.status.value}</p>')
            
            if result.status_code:
                html.append(f'<p>HTTP Status: {result.status_code}</p>')
            if result.content_type:
                html.append(f'<p>Content-Type: {result.content_type}</p>')
            if result.response_time:
                html.append(f'<p>Response Time: {result.response_time:.2f}s</p>')
            
            html.append('<div class="checks">')
            if result.https_supported is not None:
                check_class = 'check' if result.https_supported else 'cross'
                symbol = '✓' if result.https_supported else '✗'
                html.append(f'<span class="{check_class}">HTTPS: {symbol}</span>')
            
            if result.cors_supported is not None:
                check_class = 'check' if result.cors_supported else 'cross'
                symbol = '✓' if result.cors_supported else '✗'
                html.append(f'<span class="{check_class}">CORS: {symbol}</span>')
            
            if result.auth_required is not None:
                check_class = 'check' if not result.auth_required else 'cross'
                symbol = '✓' if not result.auth_required else '✗'
                html.append(f'<span class="{check_class}">No Auth: {symbol}</span>')
            
            if result.rate_limit_detected:
                html.append('<span class="cross">Rate Limiting: ✓</span>')
            html.append('</div>')
            
            if result.error_message:
                html.append(f'<p style="color: #f44336;">Error: {result.error_message}</p>')
            
            html.append('</div>')
        
        html.append("""
</body>
</html>
""")
        return '\n'.join(html)
    
    def close(self):
        """Clean up resources"""
        self.session.close()

def main():
    """Command-line interface for API validation"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Validate API endpoints')
    parser.add_argument('urls', nargs='*', help='URLs to validate')
    parser.add_argument('--readme', '-r', help='Validate APIs from README file')
    parser.add_argument('--format', '-f', choices=['text', 'json', 'html'], 
                       default='text', help='Output format')
    parser.add_argument('--output', '-o', help='Output file (default: stdout)')
    parser.add_argument('--cors', action='store_true', help='Check CORS support')
    parser.add_argument('--workers', '-w', type=int, default=10, 
                       help='Maximum concurrent workers')
    parser.add_argument('--cache-dir', help='Cache directory')
    
    args = parser.parse_args()
    
    # Initialize validator
    validator = APIValidator(
        cache_dir=args.cache_dir,
        max_workers=args.workers
    )
    
    try:
        # Get URLs to validate
        urls = []
        if args.readme:
            urls.extend(validator._extract_api_urls_from_readme(args.readme))
        if args.urls:
            urls.extend(args.urls)
        
        if not urls:
            print("Error: No URLs provided. Use --readme or provide URLs as arguments.")
            sys.exit(1)
        
        print(f"Validating {len(urls)} API endpoints...")
        
        # Validate APIs
        results = validator.validate_apis(urls, check_cors=args.cors)
        
        # Generate report
        report = validator.generate_report(results, format=args.format)
        
        # Output report
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"Report saved to {args.output}")
        else:
            print(report)
        
        # Exit with error code if any validations failed
        failed_count = sum(1 for r in results if not r.is_valid())
        if failed_count > 0:
            print(f"\nWarning: {failed_count} API(s) failed validation")
            sys.exit(1)
            
    finally:
        validator.close()

if __name__ == '__main__':
    main()