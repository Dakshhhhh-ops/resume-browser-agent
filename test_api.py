import requests
r = requests.get('https://boards-api.greenhouse.io/v1/boards/airbnb/jobs')
data = r.json()
jobs = data.get('jobs', [])
print(f'Status: {r.status_code}')
print(f'Jobs found: {len(jobs)}')
for j in jobs[:5]:
    loc = j.get('location', {}).get('name', 'N/A')
    print(f"  - {j['title']} | {loc}")
