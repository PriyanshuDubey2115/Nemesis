import aiohttp
from bs4 import BeautifulSoup
import os
import asyncio
from urllib.parse import urljoin, urlparse
from tqdm.asyncio import tqdm_asyncio
from tqdm import tqdm
import psutil
from aiohttp_socks import ProxyConnector
from pybloom_live import ScalableBloomFilter
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone
import signal
import sys
import argparse
import socket
import re
import logging
import random

# Try to import colorama, fallback to basic colors if not available
try:
    from colorama import Fore, Style, init
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False
    # ANSI escape codes for green color
    class Fore:
        GREEN = '\033[92m'
        CYAN = '\033[96m'
    class Style:
        RESET_ALL = '\033[0m'

# Initialize colorama for cross-platform colored output (if available)
if COLORAMA_AVAILABLE:
    init()

# Logging will be configured in main() to handle custom output directory
logger = logging.getLogger()

def display_ascii_banner():
    """Display the NEMESIS ASCII banner in parrot green color"""
    banner = r"""   _   ________  ______________ _________
  / | / / ____/  |/  / ____/ ___//  _/ ___/
 /  |/ / __/ / /|_/ / __/  \__ \ / / \__ \
/ /|  / /___/ /  / / /___ ___/ // / ___/ /
/_/ |_/_____/_/  /_/_____//____/___//____/"""
    
    print(Fore.GREEN + banner + Style.RESET_ALL)
    print(Fore.CYAN + "        Dark Web Crawler for .onion Sites" + Style.RESET_ALL)
    print()

def show_help():
    """Display custom help text with banner"""
    display_ascii_banner()
    print("""Usage: nemesis [OPTIONS]

Options:
  -h, --help            Show this help message and exit
  -k KEYWORD, --keyword KEYWORD
                        Crawl and filter URLs containing the specified keyword
  -t TIME, --time TIME  Set crawl duration in minutes (10-180, default: 30)
  -s START_URL, --start-url START_URL
                        Specify a custom .onion URL to start the crawl
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        Specify a custom output directory for saving files""")

CONFIG = {
    'TOR_PROXY': 'socks5://127.0.0.1:9050',
    'MONGO_URI': "mongodb://localhost:27017/",
    'DB_NAME': "dark_web_crawler",
    'COLLECTION_NAME': "crawler_page",
    'CONCURRENT_REQUESTS': 8,
    'MIN_CONCURRENT_REQUESTS': 2,
    'REQUEST_DELAY': 3,
    'MAX_RAM_USAGE_PERCENT': 70,
    'MAX_CPU_USAGE_PERCENT': 80,
    'SKIP_EXTENSIONS': ['.mp4', '.mp3', '.avi', '.mkv', '.mov', '.jpg', '.png', '.gif', '.zip', '.rar', '.pdf'],
    'DEFAULT_TIME_LIMIT_MINUTES': 30,
    'MAX_URL_LENGTH': 80,
    'DATA_DIR': 'data',
    'RAW_PAGES_DIR': 'data/raw_pages'
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive'
}

SEED_URLS = [
    "http://torlinksge6enmcyyuxjpjkoouw4oorgdgeo7ftnq3zodj7g2zxi3kyd.onion/",
    "http://deeeepv4bfndyatwkdzeciebqcwwlvgqa6mofdtsvwpon4elfut7lfqd.onion",
    "http://dirv5xzyddnqx3qkyt3vuu5doij2blzhvqrwrnimcnykgajdwxg4uhyd.onion",
    "http://jaz45aabn5vkemy4jkg4mi4syheisqn2wn2n4fsuitpccdackjwxplad.onion",
    "http://blinkxxvrydjgxao4lf6wqgxqbddw4xkawbe2zacs7sqlfxnb5ei2xid.onion/",
    "https://hidden.wiki/",
    "http://torguif5kabt7q5uff5mkw5fezkydyxhiee2ag5wzlduldcqqcibqfqd.onion/",
    "http://mb64yo6f6p6fss7sj2e7kam42apjkpn6hpcmdfpf7rp3yu4kfrhdu2qd.onion/",
    "http://gz2wuxoarcha7jorhwxncvkmrf2vtbwmxrquanc3tbhvmscblam6hmad.onion/",
    "http://kawbtpskqu7rr3t6ecz4fyutpzq7jtblin3wv5vamneryu4nwenhkgyd.onion/mediawiki/index.php?title=Tor",
]

visited = ScalableBloomFilter(initial_capacity=100000, error_rate=0.001)
queue_filter = ScalableBloomFilter(initial_capacity=100000, error_rate=0.001)
time_limit_reached = False

def signal_handler(sig, frame):
    global time_limit_reached
    logger.info("\nReceived shutdown signal. Saving progress and exiting...")
    time_limit_reached = True
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

class ResourceManager:
    @staticmethod
    def check_tor():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(('127.0.0.1', 9050))
            sock.close()
            if result != 0:
                logger.error("Tor is not running on socks5://127.0.0.1:9050.")
                sys.exit(1)
        except Exception as e:
            logger.error(f"Error checking Tor: {e}")
            sys.exit(1)
    
    @staticmethod
    def ensure_directories():
        os.makedirs(CONFIG['DATA_DIR'], exist_ok=True)
        os.makedirs(CONFIG['RAW_PAGES_DIR'], exist_ok=True)
    
    @staticmethod
    def clear_old_data(use_custom_dir=False):
        try:
            client = MongoClient(CONFIG['MONGO_URI'], serverSelectionTimeoutMS=5000)
            db = client[CONFIG['DB_NAME']]
            collection = db[CONFIG['COLLECTION_NAME']]
            collection.delete_many({})
            logger.info("Cleared MongoDB collection.")
        except Exception as e:
            logger.warning(f"Could not clear MongoDB: {e}")
        
        if not use_custom_dir:
            txt_files = ['queue.txt', 'visited_links.txt', 'keyword_matches.txt']
            for filename in txt_files:
                path = os.path.join(CONFIG['DATA_DIR'], filename)
                if os.path.exists(path):
                    try:
                        os.remove(path)
                        logger.info(f"Deleted file: {filename}")
                    except Exception as e:
                        logger.warning(f"Failed to delete {filename}: {e}")
            
            if os.path.exists(CONFIG['RAW_PAGES_DIR']):
                for file in os.listdir(CONFIG['RAW_PAGES_DIR']):
                    try:
                        file_path = os.path.join(CONFIG['RAW_PAGES_DIR'], file)
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                    except Exception as e:
                        logger.warning(f"Failed to delete raw page {file}: {e}")
            
            log_file = os.path.join(CONFIG['DATA_DIR'], 'crawler.log')
            try:
                open(log_file, 'w').close()
                logger.info("Cleared crawler.log")
            except Exception as e:
                logger.warning(f"Failed to clear crawler.log: {e}")

class MongoManager:
    def __init__(self):
        try:
            self.client = MongoClient(CONFIG['MONGO_URI'], serverSelectionTimeoutMS=5000)
            self.client.admin.command('ping')
            self.db = self.client[CONFIG['DB_NAME']]
            self.collection = self.db[CONFIG['COLLECTION_NAME']]
            self._create_indexes()
            logger.info("Connected to MongoDB successfully")
        except Exception as e:
            logger.warning(f"MongoDB connection failed ({e}).")
            self.client = self.db = self.collection = None
    
    def _create_indexes(self):
        self.collection.create_index([("url", 1)], unique=True)
        self.collection.create_index([("timestamp", -1)])
        self.collection.create_index([("status", 1)])
    
    async def save_page(self, url, status, links_found, html=None):
        if self.collection is None or status != "success":
            return
        document = {
            "url": url,
            "status": status,
            "links_found": list(links_found),
            "timestamp": datetime.now(timezone.utc),
            "domain": urlparse(url).netloc
        }
        if html:
            document["html"] = html
        try:
            self.collection.update_one({"url": url}, {"$set": document}, upsert=True)
        except Exception as e:
            logger.error(f"Error saving to MongoDB: {e}")
    
    def close(self):
        if self.client:
            self.client.close()

class URLManager:
    @staticmethod
    def load_queue():
        path = os.path.join(CONFIG['DATA_DIR'], 'queue.txt')
        if not os.path.exists(path):
            return []
        with open(path, 'r', encoding='utf-8') as f:
            return [line.strip().split('. ', 1)[1] for line in f if line.strip()]
    
    @staticmethod
    def save_queue(queue):
        path = os.path.join(CONFIG['DATA_DIR'], 'queue.txt')
        with open(path, 'w', encoding='utf-8') as f:
            for i, url in enumerate(queue, 1):
                f.write(f"{i}. {url}\n")
    
    @staticmethod
    def load_visited():
        path = os.path.join(CONFIG['DATA_DIR'], 'visited_links.txt')
        if not os.path.exists(path):
            return set()
        with open(path, 'r', encoding='utf-8') as f:
            return {line.split('. ', 1)[1].strip() for line in f if line.strip()}
    
    @staticmethod
    def save_visited(url):
        path = os.path.join(CONFIG['DATA_DIR'], 'visited_links.txt')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                existing_lines = f.readlines()
            new_number = len(existing_lines) + 1
        else:
            new_number = 1
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f"{new_number}. {url}\n")

class CrawlerUtils:
    @staticmethod
    def is_valid_onion_url(url):
        pattern = re.compile(r'^https?://[a-z2-7]{16,56}\.onion(/.*)?$', re.IGNORECASE)
        return bool(pattern.match(url)) and len(url) <= CONFIG['MAX_URL_LENGTH']
    
    @staticmethod
    def is_skippable(url):
        return not CrawlerUtils.is_valid_onion_url(url) or any(url.lower().endswith(ext) for ext in CONFIG['SKIP_EXTENSIONS'])
    
    @staticmethod
    def save_html_to_file(url, html):
        try:
            domain = urlparse(url).netloc
            filename = f"{domain}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.html"
            path = os.path.join(CONFIG['RAW_PAGES_DIR'], filename)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html)
        except Exception as e:
            tqdm.write(f'Error saving HTML for {url}: {e}')
    
    @staticmethod
    def save_keyword_url(url, keyword):
        try:
            path = os.path.join(CONFIG['DATA_DIR'], 'keyword_matches.txt')
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                number = len(lines) + 1
            else:
                number = 1
            with open(path, 'a', encoding='utf-8') as f:
                f.write(f"{number}. {url} (Keyword: {keyword})\n")
        except Exception as e:
            tqdm.write(f"Error saving keyword URL {url}: {e}")
    
    @staticmethod
    def check_keyword(html, keyword):
        if not html or not keyword:
            return False
        try:
            soup = BeautifulSoup(html, 'html.parser')
            elements = ['title', 'meta', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'span', 'div', 'a']
            text_sources = []
            for tag in elements:
                if tag == 'meta':
                    text_sources.extend(meta.get('content', '').lower() for meta in soup.find_all('meta') if meta.get('content'))
                else:
                    text_sources.extend(t.get_text(strip=True).lower() for t in soup.find_all(tag) if t.get_text(strip=True))
            return keyword.lower().strip() in " ".join(text_sources)
        except Exception as e:
            tqdm.write(f"Error checking keyword in page: {e}")
            return False
    
    @staticmethod
    async def check_system_resources():
        mem = psutil.virtual_memory().percent
        cpu = psutil.cpu_percent(interval=1)
        if mem > CONFIG['MAX_RAM_USAGE_PERCENT'] or cpu > CONFIG['MAX_CPU_USAGE_PERCENT']:
            overload = max(mem - CONFIG['MAX_RAM_USAGE_PERCENT'], cpu - CONFIG['MAX_CPU_USAGE_PERCENT']) / 100
            concurrency = max(CONFIG['MIN_CONCURRENT_REQUESTS'], int(CONFIG['CONCURRENT_REQUESTS'] * (1 - overload)))
            delay = CONFIG['REQUEST_DELAY'] * (1 + overload)
            tqdm.write(f"System overload (CPU: {cpu}%, RAM: {mem}%). Adjusting to {concurrency} concurrent requests, {delay:.1f}s delay")
            return concurrency, delay
        return CONFIG['CONCURRENT_REQUESTS'], CONFIG['REQUEST_DELAY']
    
    @staticmethod
    def extract_onion_links(html, base_url):
        soup = BeautifulSoup(html, 'html.parser')
        found_links = set()
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '.onion' in href and len(href) <= CONFIG['MAX_URL_LENGTH']:
                full_url = urljoin(base_url, href) if not href.startswith('http') else href
                if CrawlerUtils.is_valid_onion_url(full_url):
                    found_links.add(full_url)
        return found_links

async def crawl(url, session, mongo_manager, keyword=None):
    if CrawlerUtils.is_skippable(url):
        tqdm.write(f"Skipping: {url}")
        await mongo_manager.save_page(url, "skipped", set())
        return None, url, set()
    try:
        concurrency, delay = await CrawlerUtils.check_system_resources()
        async with session.get(url, headers=HEADERS, timeout=30) as response:
            if response.status == 200 and 'text/html' in response.headers.get('Content-Type', ''):
                html = await response.text()
                CrawlerUtils.save_html_to_file(url, html)
                links = CrawlerUtils.extract_onion_links(html, url)
                await mongo_manager.save_page(url, "success", links, html)
                if keyword and CrawlerUtils.check_keyword(html, keyword):
                    CrawlerUtils.save_keyword_url(url, keyword)
                    tqdm.write(f"Keyword match: {url} (Keyword: {keyword})")
                else:
                    tqdm.write(f"Crawled: {url}")
                return html, url, links
            else:
                status = f"failed_with_status_{response.status}"
                await mongo_manager.save_page(url, status, set())
                tqdm.write(f"Non-HTML: {url} (Status: {response.status})")
                return None, url, set()
    except Exception as e:
        await mongo_manager.save_page(url, f"failed_with_error_{str(e)}", set())
        tqdm.write(f"Error crawling {url}: {e}")
        return None, url, set()

async def main(args):
    global time_limit_reached
    display_ascii_banner()  # Banner now only shows once at start of main
    
    # Handle Output Directory
    base_dir = os.path.abspath(args.output_dir) if args.output_dir else os.path.abspath('data')
    keyword = args.keyword if args.keyword else "nokeyword"
    
    # Ensure base directory exists before scanning
    os.makedirs(base_dir, exist_ok=True)
    
    # Find existing keyword_* subdirs
    existing_dirs = [
        d for d in os.listdir(base_dir)
        if os.path.isdir(os.path.join(base_dir, d))
        and d.startswith(f"{keyword}_")
    ]
    
    # Extract the highest number
    numbers = []
    for d in existing_dirs:
        try:
            num = int(d.split('_')[-1])
            numbers.append(num)
        except (ValueError, IndexError):
            continue
    next_number = max(numbers, default=0) + 1
    
    # Set directory paths
    CONFIG['DATA_DIR'] = os.path.join(base_dir, f"{keyword}_{next_number}")
    CONFIG['RAW_PAGES_DIR'] = os.path.join(CONFIG['DATA_DIR'], 'raw_pages')

    # Ensure directories exist
    ResourceManager.ensure_directories()

    # Configure logging
    log_file = os.path.join(CONFIG['DATA_DIR'], 'crawler.log')
    logger.setLevel(logging.INFO)
    logger.handlers = []  # Clear existing handlers
    logger.addHandler(logging.FileHandler(log_file))
    logger.addHandler(logging.StreamHandler(sys.stderr))
    for handler in logger.handlers:
        handler.setFormatter(logging.Formatter(
            fmt='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))

    logger.info(f"Starting Nemesis crawler (Time limit: {args.time} minutes, Keyword: {args.keyword or 'None'})")
    logger.info(f"Output directory: {CONFIG['DATA_DIR']}")

    ResourceManager.check_tor()
    ResourceManager.clear_old_data(use_custom_dir=bool(args.output_dir))
    mongo_manager = MongoManager()
    start_time = datetime.now()
    time_limit = timedelta(minutes=args.time)
    queue = URLManager.load_queue()
    visited_set = URLManager.load_visited()
    
    # Initialize with either user-provided URL or random seed URL
    if not queue:
        if args.start_url and CrawlerUtils.is_valid_onion_url(args.start_url):
            queue.append(args.start_url)
            logger.info(f"Starting with user-specified URL: {args.start_url}")
        else:
            random_url = random.choice(SEED_URLS)
            queue.append(random_url)
            logger.info(f"No queue found. Starting with random seed URL: {random_url}")
            if args.start_url:
                logger.warning(f"Invalid start URL provided: {args.start_url}. Using random seed URL.")
    
    for url in visited_set:
        visited.add(url)
    connector = ProxyConnector.from_url(CONFIG['TOR_PROXY'])
    
    async with aiohttp.ClientSession(connector=connector) as session:
        tqdm.set_lock(tqdm.get_lock())
        progress = tqdm_asyncio(total=len(visited_set), desc="Crawling Progress", position=0)
        
        while not time_limit_reached:
            # Check if time limit has been reached
            if datetime.now() - start_time > time_limit:
                logger.info(f"Time limit of {args.time} minutes reached. Stopping crawler.")
                time_limit_reached = True
                break
                
            # If queue is empty, add a random seed URL to continue crawling
            if not queue:
                random_url = random.choice(SEED_URLS)
                if random_url not in visited and random_url not in queue_filter:
                    queue.append(random_url)
                    queue_filter.add(random_url)
                    logger.info(f"Queue empty. Added random seed URL: {random_url}")
                else:
                    logger.info("Queue empty and all seed URLs already visited. Waiting...")
                    await asyncio.sleep(5)
                    continue
                    
            # Process a batch of URLs
            concurrency, delay = await CrawlerUtils.check_system_resources()
            batch = queue[:concurrency]
            queue = queue[concurrency:]
            
            results = await tqdm_asyncio.gather(*[crawl(url, session, mongo_manager, args.keyword) for url in batch])
            
            for html, url, new_links in results:
                if html and new_links:
                    tqdm.write(f"Found {len(new_links)} new links on {url}")
                for link in new_links:
                    if (CrawlerUtils.is_valid_onion_url(link) and link not in visited and link not in queue_filter):
                        queue.append(link)
                        queue_filter.add(link)
                if url not in visited:
                    visited.add(url)
                    URLManager.save_visited(url)
                    progress.update(1)
                    progress.total = len(visited)
            
            URLManager.save_queue(queue)
            await asyncio.sleep(delay)
        
        progress.close()
        if time_limit_reached:
            logger.info(f"Crawling completed. Total time: {args.time} minutes.")
        else:
            logger.info("Crawling completed. No more URLs to crawl.")
    
    mongo_manager.close()

def parse_arguments():
    # Initialize colorama early
    if COLORAMA_AVAILABLE:
        init()

    # Show help if requested
    if '-h' in sys.argv or '--help' in sys.argv:
        show_help()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="Nemesis - A Dark Web Crawler for .onion Sites",
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=False  # We handle help manually
    )
    parser.add_argument(
        '-k', '--keyword',
        type=str,
        help='Crawl and filter URLs containing the specified keyword\n'
             'Saves matches to keyword_matches.txt in the output subdirectory'
    )
    parser.add_argument(
        '-t', '--time',
        type=int,
        default=CONFIG['DEFAULT_TIME_LIMIT_MINUTES'],
        help='Set crawl duration in minutes (10-180, default: 30)'
    )
    parser.add_argument(
        '-s', '--start-url',
        type=str,
        help='Specify a custom .onion URL to start the crawl\n'
             'Must be a valid .onion URL (e.g., http://example.onion)'
    )
    parser.add_argument(
        '-o', '--output-dir',
        type=str,
        help='Specify a custom output directory for saving files\n'
             'Creates a subdirectory named <keyword>_<number> (e.g., modi_1)\n'
             'Default: data/ (creates numbered subdirectories)'
    )
    parser.add_argument(
        '-h', '--help',
        action='store_true',
        help='Show this help message and exit'
    )
    
    args = parser.parse_args()
    if args.time < 10 or args.time > 180:
        print("Error: Time limit must be between 10 and 180 minutes.")
        show_help()
        sys.exit(1)
    return args

if __name__ == "__main__":
    try:
        args = parse_arguments()
        asyncio.run(main(args))
    except KeyboardInterrupt:
        logger.info("Crawler stopped by user. Data saved.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
