import sys
sys.path.append("/Users/saiful/development/python/gc-pln")
import logging
from app import load_cookies, xsrf_token, discover_rbms

logging.basicConfig(level=logging.INFO)
cookies = load_cookies()
xsrf = cookies.get("XSRF-TOKEN")
rbms = discover_rbms(cookies, xsrf)
print(f"Test found {len(rbms)} RBMs")
