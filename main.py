import requests
from bs4 import BeautifulSoup
import re

def get_page_soup(url):
    """Connects to a URL and returns a BeautifulSoup object, or None if connection fails."""
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()  # Checks for HTTP errors
        return BeautifulSoup(response.content, 'html.parser')
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to {url}: {e}")
        return None

def find_main_page_links(main_url):
    """
    Finds all relevant topic links from the main page with their correct descriptive titles.
    """
    print("Fetching links from the main page...")
    soup = get_page_soup(main_url)
    if not soup:
        return []

    content_area = soup.find('div', id='elCmsPageWrap')
    if not content_area:
        print("Could not find the main content area ('elCmsPageWrap').")
        return []

    topic_links = content_area.find_all('a', href=re.compile(r'/forums/topic/'))
    
    unique_links = {}
    for link in topic_links:
        href = link.get('href')
        link_text = ' '.join(link.get_text(strip=True).split())
        title = ""

        # If the link's text is the technical info (e.g., "[1080p...]")
        if link_text.startswith('['):
            # The real title is the text just before the link tag.
            prev_sibling = link.previous_sibling
            if prev_sibling:
                # The sibling could be a <strong> tag or just a plain text node
                if hasattr(prev_sibling, 'get_text'):
                    title = prev_sibling.get_text(strip=True)
                else: # It's a plain text node (NavigableString)
                    title = str(prev_sibling).strip()
        else:
            # Otherwise, the link text itself is the title (e.g., "Squid Game...")
            title = link_text
        
        # Clean up the title (remove trailing hyphens) and ensure it's not empty
        if title.endswith('-'):
            title = title[:-1].strip()

        if href and title:
            # Use the href as the key to prevent duplicate entries
            unique_links[href] = title
            
    # Convert the dictionary's items (href, title) to a list of (title, href) for display
    return [(title, href) for href, title in unique_links.items()]

def find_download_links(page_url):
    """
    Visits a specific topic page and extracts magnet and droplink URLs.
    """
    print(f"\nFetching download links from: {page_url}")
    soup = get_page_soup(page_url)
    if not soup:
        return

    content_div = soup.find('div', class_='cPost_contentWrap')
    if not content_div:
        print("Could not find the post content area on the page.")
        return

    # --- Extract Magnet Links ---
    print("\n--- Magnet Links ---")
    magnet_links = content_div.find_all('a', href=re.compile(r'^magnet:'))
    if not magnet_links:
        print("No magnet links found.")
    else:
        for link in magnet_links:
            previous_strong_tag = link.find_previous(['strong', 'b'])
            title = previous_strong_tag.get_text(strip=True) if previous_strong_tag else "No title found"
            print(f"Title: {title}")
            print(f"Link: {link['href']}\n")

    # --- Extract Droplinks ---
    print("\n--- Droplink URLs ---")
    script_tag = soup.find('script', type='application/ld+json')
    if script_tag and script_tag.string:
        droplinks = re.findall(r'(https://droplink\.co/\w+)', script_tag.string)
        if not droplinks:
             print("No droplinks found in the script tag.")
        else:
            text_lines = script_tag.string.split('\\n')
            for link in droplinks:
                title = "Unknown Title"
                for i, line in enumerate(text_lines):
                    if link in line and i > 0:
                        title = text_lines[i-1].strip().replace(':', '')
                        break
                print(f"Title: {title}")
                print(f"Link: {link}\n")
    else:
        print("Could not find the JSON-LD script tag to extract droplinks.")


# --- Main Script Execution ---

BASE_URL = "https://www.1tamilmv.farm/"
topic_links = find_main_page_links(BASE_URL)

if topic_links:
    print("\nPlease select a link to scrape from the list below:")
    for i, (title, href) in enumerate(topic_links[:15], 1):
        print(f"{i}. {title}")

    try:
        choice = int(input("\nEnter the number of the link you want to process: "))
        if 1 <= choice <= len(topic_links[:15]):
            # Get the correct href from the list (it's the second item in the tuple)
            selected_href = topic_links[choice - 1][1]
            find_download_links(selected_href)
        else:
            print("Invalid number. Please run the script again and select a valid number.")
    except ValueError:
        print("Invalid input. Please enter a number.")
else:
    print("\nCould not retrieve any topic links. The website structure may have changed.")
