import sys
import json
sys.path.append("/Users/saiful/development/python/gc-pln")
from app import load_cookies, REGION1_ID, REGION2_ID, REGION3_ID, SURVEY_PERIOD_ID, api_request, BASE_URL

cookies = load_cookies()
xsrf = cookies.get("XSRF-TOKEN")
url = f"{BASE_URL}/analytic/api/v2/assignment/datatable-all-user-survey-periode"

def mk_body(prefix="M", is_col=False):
    cols = []
    for c in ["id", "codeIdentity", "data1", "data2", "data3", "data4", "data5", "data6"]:
        cols.append({
            "data": c,
            "name": "", "searchable": True, "orderable": True,
            "search": {"value": prefix if (is_col and c == "data1") else "", "regex": is_col}
        })
    return {
        "draw": 1, "start": 0, "length": 1, "columns": cols,
        "search": {"value": "" if is_col else prefix, "regex": False},
        "assignmentExtraParam": {
            "region1Id": REGION1_ID, "region2Id": REGION2_ID, "region3Id": REGION3_ID, 
            "region4Id": None, "surveyPeriodId": SURVEY_PERIOD_ID,
            "assignmentErrorStatusType": -1, "filterTargetType": "TARGET_ONLY"
        }
    }

resp_col = api_request("POST", url, cookies, xsrf, json_data=mk_body("5", True))
resp_glob = api_request("POST", url, cookies, xsrf, json_data=mk_body("5", False))

print("Col Search ^5:", resp_col.get("totalHit") if resp_col else None)
print("Glob Search 5:", resp_glob.get("totalHit") if resp_glob else None)
