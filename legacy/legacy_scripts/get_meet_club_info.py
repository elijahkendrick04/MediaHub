import json
import re
import urllib.request
import time

with open('/home/user/workspace/swim-content/selected_meets.json') as f:
    selected = json.load(f)

def get_meet_club_info(meet_id):
    """Visit the meet page on SR to find host club info"""
    url = f"https://www.swimmingresults.org/meet.php?meet={meet_id}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='replace')
        return html
    except Exception as e:
        return None

# Get club info for first 20 meets
enriched = []
for i, meet in enumerate(selected):
    print(f"[{i+1}/{len(selected)}] Fetching meet {meet['meet_id']}: {meet['meet_name'][:50]}...")
    html = get_meet_club_info(meet['meet_id'])
    
    meet_info = dict(meet)
    if html:
        # Look for club name in the page
        club_match = re.search(r'Club[:\s]+<[^>]+>([^<]+)<', html)
        if not club_match:
            club_match = re.search(r'Host Club[:\s]*([^\n<]{3,50})', html)
        if not club_match:
            club_match = re.search(r'<h[12][^>]*>([^<]*(?:SC|ASC|Swimming|Swim|Aquatics)[^<]*)</h[12]>', html, re.I)
        
        # Look for promoter info
        promoter_match = re.search(r'Promoter[:\s]*([^\n<]{3,60})', html)
        
        # Look for results links
        results_links = re.findall(r'href="([^"]+)"[^>]*>[^<]*[Rr]esult[^<]*</a>', html)
        
        # Look for any PDF/document links
        doc_links = re.findall(r'href="([^"]*\.(?:pdf|PDF|htm|html|HTML|zip|ZIP|hy3|HY3)[^"]*)"', html)
        
        meet_info['host_club_raw'] = club_match.group(1).strip() if club_match else ''
        meet_info['promoter_raw'] = promoter_match.group(1).strip() if promoter_match else ''
        meet_info['results_links'] = results_links[:5]
        meet_info['doc_links'] = doc_links[:5]
        meet_info['sr_url'] = f"https://www.swimmingresults.org/meet.php?meet={meet['meet_id']}"
        
        # Extract title
        title_match = re.search(r'<title>([^<]+)</title>', html)
        meet_info['page_title'] = title_match.group(1).strip() if title_match else ''
        
    enriched.append(meet_info)
    time.sleep(0.3)

with open('/home/user/workspace/swim-content/meets_enriched.json', 'w') as f:
    json.dump(enriched, f, indent=2)

print(f"\nDone. Saved {len(enriched)} meets.")
