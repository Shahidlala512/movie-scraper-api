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

# --- Bulletproof Link Resolver (Strips out internal site loops) ---
def resolve_final_url(scraper, start_url):
    current_url = start_url
    valid_hosts = ['hubcloud', 'gdflix', 'filepress', 'drive.google', 'pixeldrain', '10file', 'katfile', 'vflix', 'embedgram', 'mdisk']
    
    for _ in range(4):
        try:
            # Agar URL me pehle se hi direct file host hai, toh wahi return kar do
            if any(host in current_url.lower() for host in valid_hosts):
                return current_url
                
            resp = scraper.get(current_url, allow_redirects=True, timeout=6)
            final_resp_url = resp.url
            
            if any(host in final_resp_url.lower() for host in valid_hosts):
                return final_resp_url
                
            if resp.status_code != 200:
                break
                
            soup = BeautifulSoup(resp.text, 'html.parser')
            next_target = None
            
            # Look for /goto/ links or direct download buttons inside the page
            for a in soup.find_all('a', href=True):
                h = a['href'].strip()
                if not h or h.startswith('#') or 'javascript:' in h:
                    continue
                    
                if h.startswith('/'):
                    domain = "https://moviesmint.app" if 'moviesmint' in current_url else "https://new5.hdhub4u.cl"
                    h = f"{domain}{h}"
                    
                if any(host in h.lower() for host in valid_hosts):
                    return h
                elif '/goto/' in h and h != current_url:
                    next_target = h
                    
            if next_target:
                current_url = next_target
            else:
                break
        except Exception:
            break
            
    # Agar link abhi bhi source website ke andar hi ghum raha hai aur bahar nahi gaya, toh None return karo taki wo list se hat jaye
    if 'moviesmint.app' in current_url or 'hdhub4u' in current_url:
        return None
        
    return current_url

@app.get("/api/links")
def get_download_links(detailUrl: str):
    scraper = get_scraper()
    try:
        resp = scraper.get(detailUrl, timeout=8)
        if resp.status_code != 200:
            return {"success": False, "error": "Could not fetch details"}
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        for junk in soup.find_all(['header', 'footer', 'aside', 'nav', 'form', 'comment']):
            junk.decompose()
            
        for junk_div in soup.find_all('div', class_=re.compile(r'sidebar|related|recommended|widgets|popular|social|share|comments|recent')):
            junk_div.decompose()
            
        final_links = []
        content_area = soup.find(['div', 'article'], class_=re.compile(r'post-content|entry-content|content|su-spoiler|post_content'))
        search_scope = content_area if content_area else soup
        
        all_a_tags = search_scope.find_all('a', href=True)
        
        for tag in all_a_tags:
            href = tag['href'].strip()
            text = tag.get_text(strip=True)
            text_lower = text.lower()
            
            if any(bad in text_lower for bad in ['telegram', 'whatsapp', 'subscribe', 'join', 'home', 'request']):
                continue
                
            qualities = []
            if '480p' in text_lower or '480p' in href.lower():
                qualities.append('480p')
            if '720p' in text_lower or '720p' in href.lower():
                qualities.append('720p')
            if '1080p' in text_lower or '1080p' in href.lower():
                qualities.append('1080p')
            if '4k' in text_lower or '2160p' in text_lower or '4k' in href.lower():
                qualities.append('4K')
            if 'batch' in text_lower or 'zip' in text_lower or 'pack' in text_lower:
                qualities.append('Batch/Zip')
                
            if not qualities and not any(k in href.lower() for k in ['/goto/', 'gdflix', 'filepress', 'drive', 'hubcloud']):
                continue
                
            if href.startswith('/'):
                domain = "https://moviesmint.app" if 'moviesmint' in detailUrl else "https://new5.hdhub4u.cl"
                href = f"{domain}{href}"
                
            resolved_url = resolve_final_url(scraper, href)
            
            # Agar link resolve hokar wapas moviesmint/hdhub4u par hi atak gaya, toh use add hi mat karo!
            if not resolved_url:
                continue
                
            quality_str = " / ".join(qualities) if qualities else "Fast Link"
            label = f"⚡ Download [{quality_str}]"
            if text and len(text) < 40 and not text_lower.startswith('download links') and not text_lower.startswith('dual audio'):
                label = f"⚡ {text}"
                
            final_links.append({
                "name": label,
                "url": resolved_url
            })
                
        seen_urls = set()
        unique_links = []
        for l in final_links:
            if l['url'] not in seen_urls:
                seen_urls.add(l['url'])
                unique_links.append(l)
                
        return {"success": True, "links": unique_links}
    except Exception as e:
        return {"success": False, "error": str(e)}
        
