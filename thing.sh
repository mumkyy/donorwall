#!/usr/bin/env bash
set -euo pipefail

# Paste your current UA and cookies here
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36'
CK='cf_clearance=aydAlYqzZxp8hjh9htQnHvA9J0TczZ8ah3VQHCLCrCw-1764977185-1.2.1.1-3ThpvuOSO0zFU5jt9a6he3TTSmg5itB7EVATPWgIoN3MLaKTcPqNIBSCymr2mf8YjzCL9HJM518e_gcHjhY_9o8NsV6KHvrXZER1ror1ea9QBTnKp_4SoOKv2ro8HGwlf_GLBP5iRMB5c9JS9hWVpKS4nCMJNf0ZcgKBxDP8Ry.SlUHfaBleyitrtnXQbNlXHWzOR_L_e7jnUU1ysTZlNNqsoLWz9yEDeVPRbyv0tkc; __cf_bm=yl98iDoKROpPsfVetbd7NLmpvSDTKtWKsLsAOFtdgwc-1764977811-1.0.1.1-x9TD3Mi_VBIUYWdYZ4ioYQeSn6TJbxLyXSbjRdtGIcGhkqzJDo2d4wO4gcabI0.5C0HJU60ecESIHTPhrO7gd_AhiQbsPAW4ce5YG3lVDEk'

INTERVAL_SECONDS=300  # 5 minutes; adjust as needed

run_once() {
  echo "Downloading at $(date)"
  curl.exe -sS -A "$UA" -H "Cookie: $CK" "https://give.njit.edu/honors-winter-gala" -o honors-winter-gala.html
  curl.exe -sS -A "$UA" -H "Cookie: $CK" "https://give.njit.edu/campaigns/72810/campaign_donors.html?show=all" -o campaign_donors_72810_all.html

  python - <<'PY'
from pathlib import Path
import sqlite3
from bs4 import BeautifulSoup

def extract_names(html_path):
    soup = BeautifulSoup(Path(html_path).read_text(encoding="utf-8"), "html.parser")
    names, seen = [], set()
    for row in soup.select("table#all-table tr.leaderboard-row"):
        td = row.find("td")
        if not td:
            continue
        div = td.find("div", class_="col-sm-6")
        name = div.get_text(" ", strip=True) if div else td.get_text(" ", strip=True)
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names

names = extract_names("campaign_donors_72810_all.html")
conn = sqlite3.connect("donors.db")
cur = conn.cursor()
cur.execute("DELETE FROM donors")
cur.executemany("INSERT INTO donors (name, amount) VALUES (?, ?)", [(n, 0) for n in names])
conn.commit()
conn.close()
print(f"Inserted {len(names)} donors")
PY
}

while true; do
  run_once
  sleep "$INTERVAL_SECONDS"
done
