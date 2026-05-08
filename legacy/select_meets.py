import json
import re
from collections import defaultdict

with open('/home/user/workspace/swim-content/all_meets_raw.json') as f:
    all_meets = json.load(f)

# Target: 7-8 meets per month, with level diversity
# Months: May 2025 to May 2026

# Key months we want to cover
target_months = [
    (5, 2025), (6, 2025), (7, 2025), (8, 2025), (9, 2025), (10, 2025),
    (11, 2025), (12, 2025), (1, 2026), (2, 2026), (3, 2026), (4, 2026), (5, 2026)
]

# Build index by month
by_month = defaultdict(list)
for m in all_meets:
    key = (m['month'], m['year'])
    by_month[key].append(m)

# Select ~7-8 meets per month with level diversity
selected = []

for month, year in target_months:
    month_meets = by_month.get((month, year), [])
    if not month_meets:
        continue
    
    # Group by level
    by_level = defaultdict(list)
    for m in month_meets:
        by_level[m['level']].append(m)
    
    month_selected = []
    
    # Try to get at least 1-2 from each level
    for level in [1, 2, 3, 4]:
        level_meets = by_level.get(level, [])
        # Prefer England meets (have club websites)
        eng_meets = [m for m in level_meets if 'Region' in m.get('region', '') or 'Wales' in m.get('region', '')]
        scot_meets = [m for m in level_meets if 'Scotland' in m.get('region', '')]
        
        # Try to pick one England/Wales meet per level
        if eng_meets:
            month_selected.append(eng_meets[0])
        elif scot_meets:
            month_selected.append(scot_meets[0])
        
        if len(month_selected) >= 8:
            break
    
    # Fill up to 7-8 if we don't have enough
    remaining = [m for m in month_meets if m not in month_selected]
    while len(month_selected) < 7 and remaining:
        month_selected.append(remaining.pop(0))
    
    selected.extend(month_selected)
    print(f"{year}-{month:02d}: {len(month_selected)} meets selected (levels: {sorted(set(m['level'] for m in month_selected))})")

print(f"\nTotal selected: {len(selected)}")

# Now we need to get the host club info for each selected meet
# visit meet.php page for each to find host club
with open('/home/user/workspace/swim-content/selected_meets.json', 'w') as f:
    json.dump(selected, f, indent=2)

# Print a summary list 
for m in selected[:20]:
    print(f"  [{m['year']}-{m['month']:02d}] L{m['level']} - {m['meet_name']} (ID: {m['meet_id']})")
