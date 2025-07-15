import aiohttp
from bs4 import BeautifulSoup
import os
import asyncio
from urllib.parse import urljoin
from tqdm.asyncio import tqdm_asyncio
import psutil
from aiohttp_socks import ProxyConnector
from pybloom_live import ScalableBloomFilter
from pymongo import MongoClient
from datetime import datetime, timedelta
import signal
import sys
import argparse
import socket

# Tor Proxy Configuration
TOR_PROXY = 'socks5://127.0.0.1:9050'

# MongoDB Configuration
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "dark_web_crawler"
COLLECTION_NAME = "crawler_page"

# Browser Headers for Anonymity
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive'
}

# Crawler Configuration
CONCURRENT_REQUESTS = 8
MIN_CONCURRENT_REQUESTS = 2
REQUEST_DELAY = 3
MAX_RAM_USAGE_PERCENT = 70
MAX_CPU_USAGE_PERCENT = 80
SKIP_EXTENSIONS = ['.mp4', '.mp3', '.avi', '.mkv', '.mov', '.jpg', '.png', '.gif', '.zip', '.rar', '.pdf']
DEFAULT_TIME_LIMIT_MINUTES = 30

# Probabilistic Data Structures
visited = ScalableBloomFilter(initial_capacity=100000, error_rate=0.001)
queue_filter = ScalableBloomFilter(initial_capacity=100000, error_rate=0.001)

# Global flag for time limit
time_limit_reached = False

def signal_handler(sig, frame):
    """Handle CTRL+C signal gracefully"""
    print("\nReceived shutdown signal. Saving progress and exiting...")
    global time_limit_reached
    time_limit_reached = True
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def check_tor():
    """Check if Tor is running on localhost:9050"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('127.0.0.1', 9050))
        sock.close()
        if result != 0:
            print("Error: Tor is not running on socks5://127.0.0.1:9050. Start Tor with 'sudo systemctl start tor'.")
            sys.exit(1)
    except Exception as e:
        print(f"Error checking Tor: {e}")
        sys.exit(1)

class MongoManager:
    def __init__(self):
        try:
            self.client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ping')  # Test connection
            self.db = self.client[DB_NAME]
            self.collection = self.db[COLLECTION_NAME]
        except Exception as e:
            print(f"Warning: MongoDB connection failed ({e}). Continuing without MongoDB storage.")
            self.client = None
            self.db = None
            self.collection = None
    
    async def save_page(self, url, status, links_found, html=None):
        """Save crawl status to MongoDB if available"""
        if self.collection is None:
            return
        document = {
            "url": url,
            "status": status,
            "links_found": list(links_found),
            "timestamp": datetime.utcnow()
        }
        if html:
            document["html"] = html
        try:
            self.collection.insert_one(document)
        except Exception as e:
            print(f"Error saving to MongoDB: {e}")
    
    def close(self):
        """Close MongoDB connection if available"""
        if self.client:
            self.client.close()

def load_queue():
    """Load URLs from queue file or return empty list"""
    if not os.path.exists('data/queue.txt'):
        return []
    with open('data/queue.txt', 'r') as f:
        return [line.strip() for line in f if line.strip()]

def save_queue(queue):
    """Save current queue to file"""
    os.makedirs('data', exist_ok=True)
    with open('data/queue.txt', 'w') as f:
        for url in queue:
            f.write(url + '\n')

def load_visited():
    """Load visited URLs from file"""
    if not os.path.exists('data/visited_links.txt'):
        return set()
    with open('data/visited_links.txt', 'r') as f:
        return set(line.strip() for line in f if line.strip())

def save_visited(url):
    """Append visited URL to file"""
    os.makedirs('data', exist_ok=True)
    with open('data/visited_links.txt', 'a') as f:
        f.write(url + '\n')

def is_skippable(url):
    """Check if URL points to a file we should skip"""
    return any(url.lower().endswith(ext) for ext in SKIP_EXTENSIONS)

def save_html_to_file(url, html):
    """Save HTML content to a file"""
    try:
        filename = ''.join(c for c in url if c.isalnum() or c in ('_', '-', '.'))[:100]
        os.makedirs('data/raw_pages', exist_ok=True)
        with open(f'data/raw_pages/{filename}.html', 'w', encoding='utf-8') as f:
            f.write(html)
    except Exception as e:
        print(f'Error saving HTML for {url}: {e}')

def save_keyword_url(url, keyword):
    """Save URL to a keyword-specific file"""
    try:
        os.makedirs('data', exist_ok=True)
        filename = 'data/keyword_matches.txt'
        with open(filename, 'a', encoding='utf-8') as f:
            f.write(f"{url} (Keyword: {keyword})\n")
    except Exception as e:
        print(f'Error saving keyword URL {url}: {e}')

def check_keyword(html, keyword):
    """Check if keyword exists in page content with improved search"""
    if not html or not keyword:
        return False
    try:
        soup = BeautifulSoup(html, 'html.parser')
        # Extract text from multiple elements for comprehensive search
        text_sources = []
        # Title
        if soup.title and soup.title.string:
            text_sources.append(soup.title.string.lower())
        # Meta tags (description, keywords)
        for meta in soup.find_all('meta'):
            if meta.get('content'):
                text_sources.append(meta['content'].lower())
        # Headings, paragraphs, and other visible text
        for tag in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'span', 'div']):
            text = tag.get_text(strip=True).lower()
            if text:
                text_sources.append(text)
        # Links text
        for link in soup.find_all('a'):
            if link.get_text(strip=True):
                text_sources.append(link.get_text(strip=True).lower())
        combined_text = " ".join(text_sources)
        # Case-insensitive keyword search
        keyword = keyword.lower().strip()
        return keyword in combined_text
    except Exception as e:
        print(f"Error checking keyword in page: {e}")
        return False

async def check_system_resources():
    """Check system resource usage and throttle if needed"""
    mem = psutil.virtual_memory().percent
    cpu = psutil.cpu_percent(interval=1)
    if mem > MAX_RAM_USAGE_PERCENT or cpu > MAX_CPU_USAGE_PERCENT:
        overload = max(mem - MAX_RAM_USAGE_PERCENT, cpu - MAX_CPU_USAGE_PERCENT) / 100
        dynamic_concurrency = max(MIN_CONCURRENT_REQUESTS, int(CONCURRENT_REQUESTS * (1 - overload)))
        dynamic_delay = REQUEST_DELAY * (1 + overload)
        print(f"System overload detected (CPU: {cpu}%, RAM: {mem}%). Reducing concurrency to {dynamic_concurrency}, delay to {dynamic_delay:.1f}s")
        return dynamic_concurrency, dynamic_delay
    return CONCURRENT_REQUESTS, REQUEST_DELAY

async def crawl(url, session, mongo_manager, keyword=None):
    """Fetch and process a single URL"""
    if is_skippable(url):
        print(f"Skipping media file: {url}")
        await mongo_manager.save_page(url, "skipped", set())
        return None, url, set()
    try:
        current_concurrency, current_delay = await check_system_resources()
        async with session.get(url, headers=headers, timeout=30) as response:
            if response.status == 200 and 'text/html' in response.headers.get('Content-Type', ''):
                html = await response.text()
                save_html_to_file(url, html)
                links_found = extract_onion_links(html, url)
                await mongo_manager.save_page(url, "success", links_found, html)
                if keyword and check_keyword(html, keyword):
                    save_keyword_url(url, keyword)
                    print(f"Keyword match found: {url} (Keyword: {keyword})")
                else:
                    print(f"Crawled: {url}")
                return html, url, links_found
            else:
                status = f"failed_with_status_{response.status}"
                await mongo_manager.save_page(url, status, set())
                print(f'Non-HTML response: {url} (Status: {response.status})')
                return None, url, set()
    except Exception as e:
        status = f"failed_with_error_{str(e)}"
        await mongo_manager.save_page(url, status, set())
        print(f'Error crawling {url}: {e}')
        return None, url, set()

def extract_onion_links(html, base_url):
    """Extract all .onion links from HTML"""
    soup = BeautifulSoup(html, 'html.parser')
    found_links = set()
    for link in soup.find_all('a', href=True):
        href = link['href']
        if '.onion' in href:
            if href.startswith('http'):
                found_links.add(href)
            else:
                found_links.add(urljoin(base_url, href))
    return found_links

async def main(args):
    """Main crawling function with dynamic resource management and time limit"""
    print(f"Starting Nemesis crawler (Time limit: {args.time} minutes, Keyword: {args.keyword or 'None'})")
    global time_limit_reached
    check_tor()
    mongo_manager = MongoManager()
    start_time = datetime.now()
    time_limit = timedelta(minutes=args.time)
    queue = load_queue()
    disk_visited = load_visited()
    for url in disk_visited:
        visited.add(url)
    if not queue:
        start_url = "http://jaz45aabn5vkemy4jkg4mi4syheisqn2wn2n4fsuitpccdackjwxplad.onion/"
        queue.append(start_url)
        print(f"No queue found. Starting with: {start_url}")
    connector = ProxyConnector.from_url(TOR_PROXY)
    async with aiohttp.ClientSession(connector=connector) as session:
        progress = tqdm_asyncio(desc="Crawling Progress")
        while queue and not time_limit_reached:
            if datetime.now() - start_time > time_limit:
                print(f"\nTime limit of {args.time} minutes reached. Stopping crawler.")
                time_limit_reached = True
                break
            current_concurrency, current_delay = await check_system_resources()
            batch = queue[:current_concurrency]
            queue = queue[current_concurrency:]
            tasks = [crawl(url, session, mongo_manager, args.keyword) for url in batch]
            results = await tqdm_asyncio.gather(*tasks)
            for html, url, new_links in results:
                if html and new_links:
                    print(f"Found {len(new_links)} new links on {url}")
                for link in new_links:
                    if link not in visited and link not in queue_filter:
                        queue.append(link)
                        queue_filter.add(link)
                if url not in visited:
                    visited.add(url)
                    save_visited(url)
                    progress.update(1)
            save_queue(queue)
            await asyncio.sleep(current_delay)
        progress.close()
        if time_limit_reached:
            print(f"Crawling paused. Saved {len(queue)} URLs to data/queue.txt.")
            if args.keyword:
                print(f"Keyword matches saved to data/keyword_matches.txt")
        else:
            print(f"Crawling completed. No more URLs to crawl.")
            if args.keyword:
                print(f"Keyword matches saved to data/keyword_matches.txt")
    mongo_manager.close()

def parse_arguments():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="Nemesis - A Dark Web Crawler for .onion Sites\n"
                    "Crawls .onion sites and supports keyword filtering.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '-k', '--keyword',
        type=str,
        help='Crawl and filter URLs containing the specified keyword\n'
             'Saves matches to data/keyword_matches.txt'
    )
    parser.add_argument(
        '-t', '--time',
        type=int,
        default=DEFAULT_TIME_LIMIT_MINUTES,
        help='Set crawl duration in minutes (10-180, recommended: 30)'
    )
    args = parser.parse_args()
    if args.time < 10 or args.time > 180:
        parser.error("Time limit must be between 10 and 180 minutes.")
    if args.time != DEFAULT_TIME_LIMIT_MINUTES:
        print(f"Recommended crawl duration is 30 minutes. You set {args.time} minutes.")
    return args

if __name__ == "__main__":
    try:
        args = parse_arguments()
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\nCrawler stopped by user. Data saved.")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)
