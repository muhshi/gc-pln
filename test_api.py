import sys
import json
import requests
from app import load_cookies, REGION3_ID, BASE_URL, SURVEY_PERIOD_ID

cookies = load_cookies()
xsrf = cookies.get('XSRF-TOKEN')
headers = {'Accept': 'application/json', 'X-XSRF-TOKEN': xsrf}

urls = [
    f"{BASE_URL}/assignment-general/api/region/get-by-parent-id?parentId={REGION3_ID}&surveyPeriodId={SURVEY_PERIOD_ID}",
    f"{BASE_URL}/assignment-general/api/region/get-by-parent-id?parentId={REGION3_ID}",
    f"{BASE_URL}/assignment-general/api/region/get-children?parentId={REGION3_ID}",
    f"{BASE_URL}/assignment-general/api/region/get-level-4?regionId={REGION3_ID}",
    f"{BASE_URL}/assignment-general/api/region/get-by-id?regionId={REGION3_ID}"
]

for u in urls:
    print(f"Testing: {u}")
    try:
        res = requests.get(u, headers=headers, cookies=cookies)
        print(f"Status: {res.status_code}")
        if res.status_code == 200:
            print(f"Data: {str(res.json())[:200]}")
    except Exception as e:
        print(f"Error: {e}")
