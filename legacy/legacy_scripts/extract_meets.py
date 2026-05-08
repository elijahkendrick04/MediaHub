import re
import urllib.request
import json
import time

def fetch_meets_for_month(month, year):
    url = f"https://www.swimmingresults.org/licensed_meets/?month={month}&year={year}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"Error fetching {month}/{year}: {e}")
        return []
    
    # Parse meet entries from HTML
    pattern = r'<a href="(meet\.php\?meet=(\d+)[^"]+)">([^<]+)</a>.*?<span class="cl-event-type">([^<]+(?:<br>[^<]+)*)</span>'
    meets = []
    rows = re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL)
    
    # Alternative pattern - grab all meet links
    meet_links = re.findall(r'href="(meet\.php\?meet=(\d+)&[^"]+)"[^>]*>([^<]+)</a>', html)
    
    for href, meet_id, name in meet_links:
        # Find level info nearby - look for the event type
        meets.append({
            'meet_id': meet_id,
            'meet_name': name.strip(),
            'month': month,
            'year': year,
            'href': href
        })
    
    return meets

def get_meet_level_info(html_chunk):
    """Extract level/course info from the table row chunk"""
    region_match = re.search(r'cl-event-type">([^<]+(?:<br>[^<]+)*)', html_chunk)
    if region_match:
        return region_match.group(1).replace('<br>', '|').strip()
    return ''

# Fetch all months from May 2025 to April 2026
all_meets = []
months = [
    (5, 2025), (6, 2025), (7, 2025), (8, 2025), (9, 2025), (10, 2025),
    (11, 2025), (12, 2025), (1, 2026), (2, 2026), (3, 2026), (4, 2026), (5, 2026)
]

for month, year in months:
    print(f"Fetching {month}/{year}...")
    url = f"https://www.swimmingresults.org/licensed_meets/?month={month}&year={year}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"Error: {e}")
        continue
    
    # Find all rows
    # Look for the table rows with meet data
    row_pattern = r'cl-event-date[^>]*>.*?cl-event-type">(.*?)</span>'
    
    # Extract meets with their full context
    meet_pattern = r'href="(meet\.php\?meet=(\d+)&[^"]+)"[^>]*>([^<]+)</a>.*?cl-event-type">([\s\S]*?)</span>'
    matches = re.findall(r'<a href="(meet\.php\?meet=(\d+)&[^"]+)"[^>]*>([^<]+)</a>.*?<span class="cl-event-type">([\s\S]*?)</span>', html)
    
    for href, meet_id, name, type_info in matches:
        type_clean = re.sub(r'<[^>]+>', '|', type_info).strip().strip('|')
        parts = [p.strip() for p in type_clean.split('|') if p.strip()]
        
        region = parts[0] if len(parts) > 0 else ''
        course = parts[1] if len(parts) > 1 else ''
        level_str = parts[2] if len(parts) > 2 else ''
        meet_type = parts[3] if len(parts) > 3 else ''
        
        # Parse level number
        level_num = 1
        level_match = re.search(r'Level\s*(\d)', level_str)
        if level_match:
            level_num = int(level_match.group(1))
        
        all_meets.append({
            'meet_id': meet_id,
            'meet_name': name.strip(),
            'month': month,
            'year': year,
            'region': region,
            'course': course,
            'level': level_num,
            'meet_type': meet_type,
            'href': f"https://www.swimmingresults.org/{href}"
        })
    
    print(f"  Found {len(matches)} meets")
    time.sleep(0.5)

# Save raw list
with open('/home/user/workspace/swim-content/all_meets_raw.json', 'w') as f:
    json.dump(all_meets, f, indent=2)

print(f"\nTotal meets found: {len(all_meets)}")

# Show distribution by month and level
from collections import Counter
dist = Counter((m['month'], m['year'], m['level']) for m in all_meets)
for key in sorted(dist.keys()):
    print(f"  {key[1]}-{key[0]:02d} Level {key[2]}: {dist[key]} meets")
