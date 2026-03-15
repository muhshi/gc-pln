from app import load_cookies, xsrf_token, fetch_assignments_page
cookies = load_cookies()
xsrf = cookies.get("XSRF-TOKEN")
resp = fetch_assignments_page(cookies, xsrf, 0, 1000, None, "1")
print(len(resp.get("searchData", [])))
