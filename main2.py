import requests
from bs4 import BeautifulSoup
import re
import time
import os
import threading
from datetime import datetime
from flask import Flask

# --- CONFIGURATION ---
# Get these from Render Environment Variables
GIST_ID = os.environ.get("GIST_ID")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

# File Names in Gist
HISTORY_FILE = "seen_movies.txt"  # The Brain (URLs)
RESULTS_FILE = "results.txt"      # The Storage (Magnets)

BASE_URL = "https://www.1tamilmv.fi/"
MAX_SIZE_MB = 1.95 * 1024  # 1.95 GB in MB
CHECK_INTERVAL = 600  # 10 Minutes

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.google.com/'
}

# --- WEB SERVER (KEEPS RENDER ALIVE) ---
app = Flask(__name__)

@app.route('/')
def home():
    return f"Bot is running. Monitoring Gist: {GIST_ID}"

# --- GIST DATABASE FUNCTIONS ---
def get_gist_data():
    """Reads both history and results from Gist."""
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        r = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=headers, timeout=10)
        if r.status_code == 200:
            files = r.json()['files']
            
            # Get History (Brain)
            history_content = files.get(HISTORY_FILE, {}).get('content', "")
            seen_set = set(filter(None, history_content.splitlines()))
            
            # Get Results (Storage)
            results_content = files.get(RESULTS_FILE, {}).get('content', "")
            
            return seen_set, results_content
            
    except Exception as e:
        print(f"❌ Read Error: {e}")
    return set(), ""

def update_gist(new_history_set, new_results_block, current_results_text):
    """Updates both files in the Gist at once."""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # 1. Prepare History (Sort it so it looks tidy)
    history_list = sorted(list(new_history_set))
    history_str = "\n".join(history_list)
    
    # 2. Prepare Results (Newest stuff goes to the TOP of the file)
    # We prepend the new block to the existing text
    final_results = new_results_block + current_results_text
    
    # Optional: Limit result file size (keep last 500 lines to prevent it getting too huge)
    # final_results = "\n".join(final_results.splitlines()[:500])

    payload = {
        "files": {
            HISTORY_FILE: {"content": history_str},
            RESULTS_FILE: {"content": final_results}
        }
    }
    
    # Only update results file if we actually have new results
    if not new_results_block:
        del payload["files"][RESULTS_FILE]

    try:
        requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=headers, json=payload, timeout=10)
        print("✅ Gist Sync Complete.")
    except Exception as e:
        print(f"❌ Save Error: {e}")

# --- PARSING LOGIC ---
def parse_size(size_str):
    if not size_str: return 0
    match = re.search(r'(\d+(?:\.\d+)?)\s*(GB|MB)', size_str, re.IGNORECASE)
    if not match: return 0
    num = float(match.group(1))
    unit = match.group(2).upper()
    return num * 1024 if unit == 'GB' else num

def get_magnets(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Bulk Filter
        magnets = soup.find_all('a', href=re.compile(r'^magnet:\?'))
        if len(magnets) > 30: return None, "TOO_MANY"

        valid = []
        for m in magnets:
            desc = "Unknown"
            prev = m.find_previous('strong')
            if prev: desc = prev.get_text(strip=True)
            
            size_match = re.search(r'(\d+(?:\.\d+)?)\s?(GB|MB)', desc, re.IGNORECASE)
            if size_match:
                mb = parse_size(size_match.group(0))
                if 0 < mb <= MAX_SIZE_MB:
                    valid.append({'link': m['href'], 'mb': mb, 'desc': desc, 'size_str': size_match.group(0)})
        
        # Sort Smallest -> Largest
        valid.sort(key=lambda x: x['mb'], reverse=False)
        return valid
    except: return []

def clean_movie_name(link_element):
    """
    Advanced logic to fix names like:
    [1080p & 720p - AVC/HEVC - (DTS5.1 - 754Kbps) - 12.5GB + Rips]
    """
    raw_text = link_element.get_text(strip=True)
    
    # If text looks normal, return it
    if not (raw_text.startswith('[') or "1080p" in raw_text or "4K" in raw_text):
        return raw_text

    # METHOD 1: Previous Sibling (Walk backwards skipping <br>)
    prev = link_element.previous_sibling
    while prev and (getattr(prev, 'name', None) == 'br' or str(prev).strip() == ''):
        prev = prev.previous_sibling
    
    if prev and isinstance(prev, str) and len(prev.strip()) > 2:
        return prev.strip().rstrip(' -')

    # METHOD 2: Parent Text Subtraction (Most reliable for formatted text)
    # Example parent: "Movie Name (2025) - [1080p...]"
    parent_text = link_element.parent.get_text()
    if raw_text in parent_text:
        # Split by the raw text and take the left side
        parts = parent_text.split(raw_text)
        if len(parts) > 0 and len(parts[0].strip()) > 2:
            candidate = parts[0].strip().rstrip(' -')
            return candidate

    return "Unknown Title"

# --- MAIN LOOP ---
def scraper():
    print("🚀 Scraper Thread Started")
    while True:
        print(f"\n[{datetime.now().strftime('%H:%M')}] Checking 1TamilMV...")
        
        # 1. Load State from Cloud
        seen_urls, current_results = get_gist_data()
        if not seen_urls and not current_results:
            print("⚠️ Warning: Could not load Gist. Retrying in 1 min...")
            time.sleep(60)
            continue

        initial_count = len(seen_urls)
        new_results_buffer = "" # Stores new text to add to results.txt

        try:
            r = requests.get(BASE_URL, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, 'html.parser')
            area = soup.find('div', attrs={'data-widgetarea': 'col1'})
            if not area: area = soup.find('div', class_='ipsType_richText')

            if area:
                links = area.find_all('a', href=True)
                count = 0
                
                for l in links:
                    if count >= 15: break
                    href = l['href'].split('#')[0]
                    
                    if "/forums/topic/" in href:
                        # Check Memory
                        if href in seen_urls: continue

                        # Clean Name
                        name = clean_movie_name(l)
                        name = name.replace(' -', '').strip()
                        
                        # Final Cleanup
                        if not name or name.startswith('['): 
                            name = "Unknown Title"

                        # Filters
                        if "PREDVD" in name.upper() or "BIGG BOSS" in name.upper():
                            print(f"🚫 Ignoring: {name}")
                            seen_urls.add(href)
                            continue

                        # Process New Movie
                        print(f"🚨 NEW: {name}")
                        magnets = get_magnets(href)

                        if magnets and magnets != "TOO_MANY":
                            # Create formatted block for results.txt
                            block = f"🎬 {name}\n"
                            block += f"🔗 {href}\n"
                            block += f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                            
                            for m in magnets:
                                block += f"   ⬇️ {m['size_str']} | {m['link']}\n"
                            
                            block += "-"*40 + "\n"
                            new_results_buffer += block
                            print(f"   ✅ Found {len(magnets)} links.")
                        else:
                            print("   ❌ No suitable links.")

                        seen_urls.add(href)
                        count += 1

                # 2. Save to Cloud if changes happened
                if len(seen_urls) > initial_count:
                    print("💾 Saving updates to Gist...")
                    update_gist(seen_urls, new_results_buffer, current_results)
                    
        except Exception as e:
            print(f"Loop Error: {e}")
            
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    # Background Thread
    t = threading.Thread(target=scraper)
    t.daemon = True
    t.start()
    
    # Web Server
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
