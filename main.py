from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import cloudscraper
from bs4 import BeautifulSoup
import re
from urllib.parse import quote_plus

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_scraper():
    return cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

@app.get("/")
def home():
    return {"status": "Multi-Source Movie Scraper API Ready"}

# --- Clean Scraper Logic (Filters out Logos, Apps & Banners) ---
def scrape_site(scraper, base_url, query):
    encoded_query = quote_plus(query)
    target_url = f"{base_url}/?s={encoded_query}"
    movies = []
    try:
        resp = scraper.get(target_url, timeout=8)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            for a_tag in soup.find_all('a', href=True):
                img_tag = a_tag.find('img')
                if img_tag:
                    href = a_tag['href']
                    
                    # Ignore unwanted system/category links
                    if any(x in href for x in ['/category/', '/tag/', '/page/', 'wp-login', 'whatsapp', 'telegram', 'facebook', 'instagram', '#']):
                        continue
                        
                    poster = img_tag.get('src') or img_tag.get('data-src') or img_tag.get('data-lazy-src')
                    if not poster or poster.startswith('data:'):
                        poster = img_tag.get('data-src') or img_tag.get('data-lazy-src')
                        
                    title = img_tag.get('alt') or img_tag.get('title') or a_tag.get_text(strip=True)
                    
                    if not title or len(title) < 2:
                        parent = a_tag.find_parent(['article', 'div'])
                        if parent:
                            title_elem = parent.find(['h2', 'h3', 'h4', 'span'], class_=re.compile(r'title|name|heading|entry'))
                            if title_elem:
                                title = title_elem.get_text(strip=True)
                                
                    if title:
                        clean_t_lower = title.lower()
                        # Strict filtering to remove logos, apps, and promotional banners
                        unwanted_keywords = [
                            'logo', 'app', 'android', 'apk', 'telegram', 'whatsapp', 
                            'channel', 'join', 'advertisement', 'banner', 'dmca', 'contact'
                        ]
                        if any(k in clean_t_lower for k in unwanted_keywords):
                            continue
                    
                    if href and poster and title:
                        if not href.startswith('http'):
                            href = f"{base_url}{href}"
                            
                        movies.append({
                            "title": title.strip(),
                            "poster": poster,
                            "pageUrl": href
                        })
    except Exception as e:
        print(f"Error scraping {base_url}:", e)
        
    return movies

# --- Combined Search Route ---
@app.get("/api/search")
def search_movies(query: str = "Hindi"):
    scraper = get_scraper()
    all_movies = []
    
    mint_results = scrape_site(scraper, "https://moviesmint.app", query)
    all_movies.extend(mint_results)
    
    hdhub_results = scrape_site(scraper, "https://new5.hdhub4u.cl", query)
    all_movies.extend(hdhub_results)
    
    seen_titles = set()
    unique_movies = []
    for m in all_movies:
        clean_title = re.sub(r'[^a-zA-Z0-9]', '', m['title'].lower())
        if clean_title not in seen_titles and len(clean_title) > 2:
            seen_titles.add(clean_title)
            unique_movies.append(m)
            
    return {
        "success": True, 
        "count": len(unique_movies), 
        "data": unique_movies
    }

# --- Resolve Final Links ---
def resolve_final_url(scraper, url):
    current_url = url
    for _ in range(3):
        try:
            resp = scraper.get(current_url, allow_redirects=True, timeout=6)
            if resp.status_code != 200:
                break
            
            if 'moviesmint.app' not in resp.url and 'hdhub4u' not in resp.url:
                return resp.url
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            next_url = None
            
            for a in soup.find_all('a', href=True):
                h = a['href'].strip()
                if not h or h.startswith('#') or 'javascript:' in h:
                    continue
                    
                if h.startswith('/'):
                    parsed_domain = "https://moviesmint.app" if 'moviesmint' in current_url else "https://new5.hdhub4u.cl"
                    full_h = f"{parsed_domain}{h}"
                else:
                    full_h = h
                    
                if 'moviesmint.app' not in full_h and 'hdhub4u' not in full_h:
                    return full_h
                elif '/goto/' in full_h and full_h != current_url:
                    next_url = full_h
                    
            if next_url:
                current_url = next_url
            else:
                break
        except Exception:
            break
    return current_url

# --- Clean Download Links Route (Prevents Mixing Related Posts) ---
@app.get("/api/links")
def get_download_links(detailUrl: str):
    scraper = get_scraper()
    try:
        resp = scraper.get(detailUrl)
        if resp.status_code != 200:
            return {"success": False, "error": "Could not fetch details"}
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Remove entire sections that contain unrelated or sidebar links
        for junk in soup.find_all(['header', 'footer', 'aside', 'nav', 'form', 'comment']):
            junk.decompose()
            
        for junk_div in soup.find_all('div', class_=re.compile(r'sidebar|related|recommended|widgets|popular|social|share|comments|recent')):
            junk_div.decompose()
            
        final_links = []
        
        # Focus strictly on the main post content area
        content_area = soup.find(['div', 'article'], class_=re.compile(r'post-content|entry-content|content|su-spoiler|post_content'))
        search_scope = content_area if content_area else soup
        
        all_a_tags = search_scope.find_all('a', href=True)
        
        for tag in all_a_tags:
            href = tag['href'].strip()
            text = tag.get_text(strip=True).lower()
            
            valid_keywords = ['480p', '720p', '1080p', '4k', 'gdrive', 'batch', 'zip', 'dual audio', 'episode', 'download']
            is_valid_download = any(k in text for k in valid_keywords) or any(k in href.lower() for k in ['/goto/', 'gdflix', 'filepress', 'drive', 'hubcloud'])
            
            if not is_valid_download or len(text) < 2:
                continue
                
            if href.startswith('/'):
                domain = "https://moviesmint.app" if 'moviesmint' in detailUrl else "https://new5.hdhub4u.cl"
                href = f"{domain}{href}"
                
            resolved_url = resolve_final_url(scraper, href)
            
            upper_text = tag.get_text(strip=True)
            label = upper_text if upper_text else "Download Link"
            
            if "480p" in text:
                label = "⚡ Download 480p [Fast Link]"
            elif "720p" in text:
                label = "⚡ Download 720p [Fast Link]"
            elif "1080p" in text:
                label = "⚡ Download 1080p [Fast Link]"
            elif "4k" in text:
                label = "⚡ Download 4K [Fast Link]"
            elif "episode" in text:
                label = f"📺 {upper_text}"
                
            final_links.append({
                "name": label,
                "url": resolved_url
            })
                
        seen = set()
    
        unique_links = []
        for l in final_links:
            if l['url'] not in seen:
                seen.add(l['url'])
                unique_links.append(l)
                
        return {"success": True, "links": unique_links}
    except Exception as e:
        return {"success": False, "error": str(e)}
    
