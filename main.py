from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import cloudscraper
from bs4 import BeautifulSoup
import re

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
    return {"status": "Movie Scraper API Ready"}

@app.get("/api/search")
def search_movies(query: str = "Hindi"):
    scraper = get_scraper()
    target_url = f"https://moviesmint.app/?s={query}"
    
    try:
        resp = scraper.get(target_url)
        if resp.status_code != 200:
            return {"success": False, "error": f"Failed status {resp.status_code}"}
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        movies = []
        
        articles = soup.find_all(['article', 'div'], class_=re.compile(r'post|item|movie|entry'))
        
        for item in articles[:15]:
            link_tag = item.find('a', href=True)
            img_tag = item.find('img')
            
            if link_tag and img_tag:
                href = link_tag['href']
                poster = img_tag.get('src') or img_tag.get('data-src') or img_tag.get('data-lazy-src')
                title = img_tag.get('alt') or img_tag.get('title') or link_tag.get_text(strip=True)
                
                if href and poster and not any(x in href for x in ['/category/', '/tag/', '/page/']):
                    movies.append({
                        "title": title.strip(),
                        "poster": poster,
                        "pageUrl": href
                    })
                    
        return {"success": True, "count": len(movies), "data": movies}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/links")
def get_download_links(detailUrl: str):
    scraper = get_scraper()
    
    try:
        resp = scraper.get(detailUrl)
        if resp.status_code != 200:
            return {"success": False, "error": "Could not fetch details"}
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        for element in soup.find_all(['header', 'footer', 'aside', 'nav', 'form', 'comment']):
            element.decompose()
            
        for junk_div in soup.find_all('div', class_=re.compile(r'sidebar|related|recommended|widgets|popular|social|share|comments')):
            junk_div.decompose()
            
        final_links = []
        
        content_area = soup.find(['div', 'article'], class_=re.compile(r'post-content|entry-content|content|su-spoiler'))
        search_scope = content_area if content_area else soup
        
        all_a_tags = search_scope.find_all('a', href=True)
        
        for tag in all_a_tags:
            href = tag['href'].strip()
            text = tag.get_text(strip=True).lower()
            
            valid_keywords = ['480p', '720p', '1080p', '4k', 'gdrive', 'batch', 'zip', 'dual audio']
            is_valid_download = any(k in text for k in valid_keywords) or any(k in href.lower() for k in ['/goto/', 'gdflix', 'filepress', 'drive'])
            
            if not is_valid_download or len(text) < 3 or 'moviesmint.app' in href and '/goto/' not in href:
                continue
                
            if href.startswith('/'):
                href = f"https://moviesmint.app{href}"
                
            resolved_url = href
            if '/goto/' in href:
                try:
                    goto_resp = scraper.get(href, allow_redirects=True, timeout=5)
                    if goto_resp.status_code == 200 and 'moviesmint.app' not in goto_resp.url:
                        resolved_url = goto_resp.url
                    else:
                        resolved_url = href
                except Exception:
                    resolved_url = href
            
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
                
            final_links.append({
                "name": label,
                "url": resolved_url
            })
                
        seen = set()
        unique_links = []
        for l in final_links:
            if l['url'] not in seen and 'moviesmint.app/?s=' not in l['url']:
                seen.add(l['url'])
                unique_links.append(l)
                
        return {"success": True, "links": unique_links}
    except Exception as e:
        return {"success": False, "error": str(e)}
        
