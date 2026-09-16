@app.get("/api/links")
def get_download_links(detailUrl: str):
    scraper = get_scraper()
    
    try:
        resp = scraper.get(detailUrl)
        if resp.status_code != 200:
            return {"success": False, "error": "Could not fetch details"}
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Remove header, footer, sidebar, and comments completely to avoid junk links
        for element in soup.find_all(['header', 'footer', 'aside', 'nav', 'form', 'comment']):
            element.decompose()
            
        for junk_div in soup.find_all('div', class_=re.compile(r'sidebar|related|recommended|widgets|popular|social|share|comments')):
            junk_div.decompose()
            
        final_links = []
        
        # Look specifically inside content area where download buttons reside
        content_area = soup.find(['div', 'article'], class_=re.compile(r'post-content|entry-content|content|su-spoiler'))
        search_scope = content_area if content_area else soup
        
        all_a_tags = search_scope.find_all('a', href=True)
        
        for tag in all_a_tags:
            href = tag['href'].strip()
            text = tag.get_text(strip=True).lower()
            
            # Strict filtering: Only target actual quality/download keywords
            valid_keywords = ['480p', '720p', '1080p', '4k', 'gdrive', 'batch', 'zip', 'dual audio']
            is_valid_download = any(k in text for k in valid_keywords) or any(k in href.lower() for k in ['/goto/', 'gdflix', 'filepress', 'drive'])
            
            # Reject generic "Download Links" text or homepage links
            if not is_valid_download or len(text) < 3 or 'moviesmint.app' in href and '/goto/' not in href:
                continue
                
            if href.startswith('/'):
                href = f"https://moviesmint.app{href}"
                
            # Resolve /goto/ links carefully
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
            
            # Clean up label formatting
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
                
        # Deduplicate links
        seen = set()
        unique_links = []
        for l in final_links:
            if l['url'] not in seen and 'moviesmint.app/?s=' not in l['url']:
                seen.add(l['url'])
                unique_links.append(l)
                
        return {"success": True, "links": unique_links}
    except Exception as e:
        return {"success": False, "error": str(e)}
        
