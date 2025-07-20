Nemesis - Dark Web Crawler
Nemesis is a Python-based dark web crawler for .onion sites, designed to crawl Tor hidden services, save HTML content, and filter pages by keywords. It uses Tor for anonymity, MongoDB for storage, and supports concurrent crawling with system resource monitoring.
Features

Crawls .onion websites via Tor proxy.
Saves HTML content and extracted links to MongoDB and local files.
Filters pages by keyword (e.g., crypto).
Configurable output directories (e.g., crypto_1).
System resource monitoring to prevent overload.
Colorful ASCII banner in parrot green.

Prerequisites

Linux (e.g., Kali, Ubuntu)
Tor (socks5://127.0.0.1:9050)
MongoDB
Python 3.8+
Git

Installation
Option 1: Install via Git Clone

Clone the Repository:
git clone https://github.com/PriyanshuDubey2115/Nemesis.git
cd Nemesis


Run Setup Script:
chmod +x setup.sh
./setup.sh

This installs dependencies, sets up a virtual environment, and configures the nemesis command globally.

Verify Installation:
nemesis -h



Option 2: Install via APT (Debian/Ubuntu)

Add Repository (if hosted):sudo add-apt-repository ppa:priyanshudubey2115/nemesis
sudo apt-get update


Install Nemesis:sudo apt-get install nemesis


Verify Installation:nemesis -h



Usage
Run Nemesis with optional arguments:
nemesis -k <keyword> -t <time_in_minutes> -s <start_url> -o <output_dir>


-k, --keyword: Filter pages containing the keyword (e.g., crypto).
-t, --time: Crawl duration in minutes (10–180, default: 30).
-s, --start-url: Starting .onion URL (e.g., http://example.onion).
-o, --output-dir: Output directory (creates <keyword>_<number> subdirectory).

Example:
nemesis -k crypto -t 10 -s http://4p6i33oqj6wgvzgzczyqlueav3tz456rdu632xzyxbnhq4gpsriirtqd.onion/ -o ~/Downloads/test

Output is saved to ~/Downloads/test/crypto_1/ (e.g., queue.txt, visited_links.txt, keyword_matches.txt, crawler.log, raw_pages/).
Troubleshooting

Tor/MongoDB not running:sudo systemctl start tor
sudo systemctl start mongodb
sudo systemctl status tor
sudo systemctl status mongodb


Permission issues:chmod -R u+w ~/Downloads/test


Dependencies:Ensure all Python dependencies are installed:pip install -r requirements.txt



Development

Directory Structure:
nemesis.py: Main crawler script.
setup.sh: Installation script.
requirements.txt: Python dependencies.
debian/: Files for Debian packaging.


Contributing:Fork the repository, make changes, and submit a pull request.

License
MIT License. See LICENSE for details.
Contact

GitHub: PriyanshuDubey2115
Issues: Report bugs or feature requests
