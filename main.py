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
    return {"status": "Multi-Source Movie Detail API Ready"}

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

def resolve_final_url(scraper, start_url):
    current_url = start_url
    for _ in range(3):
        try:
            resp = scraper.get(current_url, allow_redirects=True, timeout=5)
            final_resp_url = resp.url
            if 'moviesmint.app' not in final_resp_url and 'hdhub4u' not in final_resp_url:
                return final_resp_url
            if resp.status_code != 200:
                break
            soup = BeautifulSoup(resp.text, 'html.parser')
            next_target = None
            for a in soup.find_all('a', href=True):
                h = a['href'].strip()
                if not h or h.startswith('#') or 'javascript:' in h:
                    continue
                if h.startswith('/'):
                    domain = "https://moviesmint.app" if 'moviesmint' in current_url else "https://new5.hdhub4u.cl"
                    h = f"{domain}{h}"
                if 'moviesmint.app' not in h and 'hdhub4u' not in h:
                    return h
                elif '/goto/' in h and h != current_url:
                    next_target = h
            if next_target:
                current_url = next_target
            else:
                break
        except Exception:
            break
    return current_url

@app.get("/api/links")
def get_links_alias(detailUrl: str):
    return get_movie_detail(detailUrl)

# --- Advanced Detail Page Scraper (Metadata + Screenshots + Packs + Episodes) ---
@app.get("/api/movie-detail")
def get_movie_detail(detailUrl: str):
    scraper = get_scraper()
    try:
        resp = scraper.get(detailUrl, timeout=9)
        if resp.status_code != 200:
            return {"success": False, "error": "Could not fetch movie page"}
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 1. Title & Poster
        title_elem = soup.find(['h1', 'h2'], class_=re.compile(r'title|entry-title'))
        title = title_elem.get_text(strip=True) if title_elem else "Unknown Title"
        
        content_area = soup.find(['div', 'article'], class_=re.compile(r'post-content|entry-content|content|su-spoiler|post_content'))
        search_scope = content_area if content_area else soup
        
        poster_img = search_scope.find('img')
        poster = poster_img.get('src') or poster_img.get('data-src') if poster_img else ""
        if poster and poster.startswith('/'):
            domain = "https://moviesmint.app" if 'moviesmint' in detailUrl else "https://new5.hdhub4u.cl"
            poster = f"{domain}{poster}"

        # 2. Metadata Extraction (Director, Genre, Release Date, Cast, IMDb, Audio)
        full_text = search_scope.get_text()
        
        def extract_meta(pattern, text):
            match = re.search(pattern, text, re.IGNORECASE)
            return match.group(1).strip() if match else "N/A"

        imdb = extract_meta(r'IMDb Rating:\s*([^\n]+)', full_text)
        if imdb == "N/A":
            imdb = extract_meta(r'Rating:\s*([0-9\.]+/?10)', full_text)
            
        audio = extract_meta(r'Audio Languages?:\s*([^\n]+)', full_text)
        director = extract_meta(r'Director:\s*([^\n]+)', full_text)
        genre = extract_meta(r'Genre:\s*([^\n]+)', full_text)
        release_date = extract_meta(r'Release Date:\s*([^\n]+)', full_text)
        cast = extract_meta(r'Cast:\s*([^\n]+)', full_text)
        
        # Description / Synopsis
        p_tags = search_scope.find_all('p')
        synopsis = ""
        for p in p_tags:
            txt = p.get_text(strip=True)
            if len(txt) > 80 and not any(k in txt.lower() for k in ['download', 'click', 'telegram', 'quality']):
                synopsis = txt
                break

        # 3. Screenshots Gallery
        screenshots = []
        for img in search_scope.find_all('img'):
            img_src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if img_src and img_src != poster and not any(bad in img_src.lower() for bad in ['logo', 'icon', 'emoji', 'button', 'banner']):
                if not img_src.startswith('http'):
                    domain = "https://moviesmint.app" if 'moviesmint' in detailUrl else "https://new5.hdhub4u.cl"
                    img_src = f"{domain}{img_src}"
                if img_src not in screenshots:
                    screenshots.append(img_src)
        # Limit screenshots to prevent clutter
        screenshots = screenshots[:6]

        # 4. Links Categorization (Qualities, Packs, Episodes)
        qualities = [] # For movies: 480p, 720p, 1080p with sizes
        packs = []     # For series batches / packs
        episodes = []  # For web series individual episodes

        for a in search_scope.find_all('a', href=True):
            href = a['href'].strip()
            text = a.get_text(strip=True)
            text_lower = text.lower()
            
            if any(bad in text_lower for bad in ['telegram', 'whatsapp', 'subscribe', 'join', 'home', 'request', 'dmca', 'trailer']):
                continue
                
            if not href or href.startswith('#') or 'javascript:' in href:
                continue
                
            if href.startswith('/'):
                domain = "https://moviesmint.app" if 'moviesmint' in detailUrl else "https://new5.hdhub4u.cl"
                href = f"{domain}{href}"

            # Check for file size inside text or parent text (e.g., "260MB", "1.2GB")
            parent_text = a.parent.get_text() if a.parent else text
            size_match = re.search(r'([0-9\.]+\s*(?:MB|GB))', parent_text, re.IGNORECASE)
            size_str = size_match.group(1) if size_match else ""

            resolved_url = resolve_final_url(scraper, href)
            if not resolved_url:
                continue

            link_item = {
                "name": text if len(text) < 45 else "Download Link",
                "size": size_str,
                "url": resolved_url
            }

            # Categorize
            if 'episode' in text_lower or 'ep ' in text_lower or re.search(r'\bep\s*\d+\b', text_lower):
                episodes.append(link_item)
            elif 'pack' in text_lower or 'batch' in text_lower or 'zip' in text_lower or '10bit' in text_lower or 'season' in text_lower:
                packs.append(link_item)
            elif '480p' in text_lower or '720p' in text_lower or '1080p' in text_lower or '4k' in text_lower:
                # Determine specific quality label
                q_label = "480p"
                if '1080p' in text_lower: q_label = "1080p"
                elif '720p' in text_lower: q_label = "720p"
                elif '4k' in text_lower or '2160p' in text_lower: q_label = "4K"
                
                qualities.append({
                    "quality": q_label,
                    "size": size_str,
                    "name": text,
                    "url": resolved_url
                })
            else:
                if len(qualities) < 4:
                    qualities.append({
                        "quality": "Fast Link",
                        "size": size_str,
                        "name": text if text else "Download",
                        "url": resolved_url
                    })

        return {
            "success": True,
            "title": title,
            "poster": poster,
            "synopsis": synopsis,
            "imdb": imdb,
            "audio": audio,
            "director": director,
            "genre": genre,
            "releaseDate": release_date,
            "cast": cast,
            "screenshots": screenshots,
            "qualities": qualities,
            "packs": packs,
            "episodes": episodes
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
                
