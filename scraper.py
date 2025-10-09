#!/usr/bin/env python3
"""
Craigslist Web Scraper
Searches Craigslist for similar items and extracts listing data
"""

import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import quote_plus, urljoin
import re
from typing import List, Dict, Optional

class CraigslistScraper:
    """Scraper for Craigslist listings"""
    
    BASE_URLS = {
        'vermont': 'https://vermont.craigslist.org',
        'newhampshire': 'https://nh.craigslist.org',
        'boston': 'https://boston.craigslist.org'
    }
    
    def __init__(self, region='vermont', max_results=10):
        """
        Initialize scraper
        
        Args:
            region: Craigslist region (vermont, newhampshire, boston)
            max_results: Maximum number of results to return
        """
        self.base_url = self.BASE_URLS.get(region, self.BASE_URLS['vermont'])
        self.max_results = max_results
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
    
    def search(self, query: str) -> List[Dict]:
        """
        Search Craigslist for items matching query
        
        Args:
            query: Search term
            
        Returns:
            List of dictionaries containing listing data
        """
        encoded_query = quote_plus(query)
        search_url = f"{self.base_url}/search/sss?query={encoded_query}&sort=rel"
        
        print(f"Searching Craigslist: {search_url}")
        
        try:
            response = self.session.get(search_url, timeout=10)
            response.raise_for_status()
            
            # Debug: Save the HTML to see what we're getting
            print(f"Response status: {response.status_code}")
            print(f"Response length: {len(response.content)} bytes")
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Try multiple possible selectors for listings
            # New Craigslist uses different class names
            listings = []
            
            # Try new gallery view format
            listings = soup.select('li.cl-static-search-result')
            print(f"Found {len(listings)} listings with selector 'li.cl-static-search-result'")
            
            if not listings:
                # Try older format
                listings = soup.select('li.result-row')
                print(f"Found {len(listings)} listings with selector 'li.result-row'")
            
            if not listings:
                # Try even more generic
                listings = soup.find_all('li', class_=re.compile(r'result|search-result'))
                print(f"Found {len(listings)} listings with regex pattern")
            
            if not listings:
                print("DEBUG: No listings found. Saving HTML for inspection...")
                with open('/tmp/craigslist_debug.html', 'w', encoding='utf-8') as f:
                    f.write(soup.prettify())
                print("HTML saved to /tmp/craigslist_debug.html")
                
                # Print first 2000 chars to see structure
                print("\nFirst 2000 characters of page:")
                print(soup.prettify()[:2000])
                return []
            
            results = []
            for listing in listings[:self.max_results]:
                try:
                    listing_data = self._parse_listing(listing)
                    if listing_data:
                        results.append(listing_data)
                        print(f"  ✓ Found: {listing_data['title'][:50]}...")
                        
                        # Be polite - small delay between parsing
                        time.sleep(0.5)
                        
                except Exception as e:
                    print(f"  ✗ Error parsing listing: {e}")
                    continue
            
            print(f"Successfully parsed {len(results)} listings")
            return results
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching search results: {e}")
            return []
    
    def _parse_listing(self, listing_element) -> Optional[Dict]:
        """
        Parse a single listing element
        
        Args:
            listing_element: BeautifulSoup element containing listing
            
        Returns:
            Dictionary with listing data or None if parsing fails
        """
        try:
            # Try to find the link - multiple possible locations
            link_element = (
                listing_element.find('a', class_='posting-title') or
                listing_element.find('a', class_='titlestring') or
                listing_element.select_one('a[href*="/d/"]') or
                listing_element.find('a')
            )
            
            if not link_element:
                print("  No link found in listing")
                return None
            
            url = link_element.get('href')
            if not url:
                return None
            
            # Make URL absolute if relative
            if url and not url.startswith('http'):
                url = urljoin(self.base_url, url)
            
            # Extract title - try multiple approaches
            title = None
            
            # Try getting from the link text
            if link_element.get_text(strip=True):
                title = link_element.get_text(strip=True)
            
            # Try finding title element
            if not title:
                title_element = (
                    listing_element.find('span', class_='label') or
                    listing_element.find('div', class_='title') or
                    listing_element.find('h3')
                )
                if title_element:
                    title = title_element.get_text(strip=True)
            
            if not title:
                print("  No title found in listing")
                return None
            
            # Extract price - try multiple selectors
            price = None
            price_element = (
                listing_element.find('span', class_='priceinfo') or
                listing_element.find('span', class_='price') or
                listing_element.select_one('[class*="price"]')
            )
            
            if price_element:
                price_text = price_element.get_text(strip=True)
                # Extract numeric value from price string
                price_match = re.search(r'\$?(\d+(?:,\d{3})*(?:\.\d{2})?)', price_text)
                if price_match:
                    price = float(price_match.group(1).replace(',', ''))
            
            # Extract location
            location = None
            location_element = (
                listing_element.find('span', class_='meta') or
                listing_element.find('div', class_='location') or
                listing_element.select_one('[class*="location"]')
            )
            if location_element:
                location = location_element.get_text(strip=True)
            
            # Extract posting date
            posted_date = None
            date_element = (
                listing_element.find('time') or
                listing_element.find('span', class_='date') or
                listing_element.select_one('[datetime]')
            )
            if date_element:
                posted_date = date_element.get('datetime') or date_element.get_text(strip=True)
            
            print(f"  Parsed basic info - Title: {title[:30]}..., Price: ${price}, URL: {url}")
            
            # Fetch full listing page for more details
            detailed_data = self._fetch_listing_details(url)
            
            return {
                'title': title,
                'url': url,
                'price': price,
                'location': location,
                'posted_date': posted_date,
                'description': detailed_data.get('description'),
                'condition': detailed_data.get('condition'),
                'measurements': detailed_data.get('measurements'),
                'image_url': detailed_data.get('image_url')
            }
            
        except Exception as e:
            print(f"Error in _parse_listing: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _fetch_listing_details(self, url: str) -> Dict:
        """
        Fetch detailed information from individual listing page
        
        Args:
            url: URL of the listing
            
        Returns:
            Dictionary with detailed listing data
        """
        details = {
            'description': None,
            'condition': None,
            'measurements': None,
            'image_url': None
        }
        
        try:
            print(f"  Fetching details from: {url}")
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract description
            description_element = soup.find('section', id='postingbody')
            if description_element:
                # Remove the "QR Code Link to This Post" text
                for qr in description_element.find_all('div', class_='print-qrcode-container'):
                    qr.decompose()
                details['description'] = description_element.get_text(strip=True)
            
            # Extract condition from attributes
            attr_groups = soup.find_all('p', class_='attrgroup')
            for group in attr_groups:
                for span in group.find_all('span'):
                    text = span.get_text(strip=True)
                    # Look for condition
                    if 'condition:' in text.lower():
                        condition_match = re.search(r'condition:\s*(\w+)', text, re.IGNORECASE)
                        if condition_match:
                            details['condition'] = condition_match.group(1).title()
                    
                    # Look for dimensions/measurements
                    if any(dim in text.lower() for dim in ['dimension', 'size', 'measurement', '"', 'inches', 'feet', 'cm', 'mm']):
                        details['measurements'] = text
            
            # Extract first image - try multiple selectors
            image_element = (
                soup.find('div', class_='slide first visible') or
                soup.find('div', class_='slide') or
                soup.select_one('.gallery img') or
                soup.find('img', src=re.compile(r'images\.craigslist\.org'))
            )
            
            if image_element:
                if image_element.name == 'img':
                    details['image_url'] = image_element.get('src')
                else:
                    img = image_element.find('img')
                    if img and img.get('src'):
                        details['image_url'] = img['src']
            
            print(f"    Details: Desc={bool(details['description'])}, Condition={details['condition']}, Image={bool(details['image_url'])}")
            
            # Small delay to be respectful
            time.sleep(1)
            
        except Exception as e:
            print(f"  Error fetching listing details from {url}: {e}")
        
        return details


def scrape_craigslist(query: str, region='vermont', max_results=10) -> List[Dict]:
    """
    Convenience function to scrape Craigslist
    
    Args:
        query: Search query
        region: Craigslist region
        max_results: Maximum results to return
        
    Returns:
        List of listing dictionaries
    """
    scraper = CraigslistScraper(region=region, max_results=max_results)
    return scraper.search(query)


if __name__ == '__main__':
    # Test the scraper
    import sys
    
    if len(sys.argv) > 1:
        query = ' '.join(sys.argv[1:])
    else:
        query = 'counter top'
    
    print(f"Testing Craigslist scraper with query: '{query}'")
    print("=" * 60)
    
    results = scrape_craigslist(query, region='vermont', max_results=5)
    
    print("\n" + "=" * 60)
    print(f"Results: {len(results)} listings found")
    print("=" * 60)
    
    for i, result in enumerate(results, 1):
        print(f"\n{i}. {result['title']}")
        print(f"   Price: ${result['price']}" if result['price'] else "   Price: Not listed")
        print(f"   Location: {result['location']}")
        print(f"   URL: {result['url']}")
        if result['condition']:
            print(f"   Condition: {result['condition']}")
        if result['measurements']:
            print(f"   Measurements: {result['measurements']}")
        if result['description']:
            desc_preview = result['description'][:100].replace('\n', ' ')
            print(f"   Description: {desc_preview}...")
