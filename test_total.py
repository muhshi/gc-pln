from app import load_cookies, BASE_URL, SURVEY_PERIOD_ID, api_request, REGION3_ID, fetch_assignments_page

cookies = load_cookies()
xsrf = cookies.get("XSRF-TOKEN")
resp = fetch_assignments_page(cookies, xsrf, 0, 10, None, "")
if resp:
    print("Empty search string total hits:", resp.get("totalHit"))
