# donor_wall/routes.py

import os
from urllib.parse import urljoin
import re
from pathlib import Path

from flask import Blueprint, render_template, request, make_response, jsonify
from db import get_db
from bs4 import BeautifulSoup
import requests

donor_wall_bp = Blueprint('donor_wall', __name__, template_folder='templates')

#############################
# Helper Functions
#############################

def parse_amount_to_number(amount):
    """
    Convert an amount string (e.g., "$1,200") to a float.
    If the amount is None or cannot be parsed, return 0.
    """
    if not amount:
        return 0
    # Remove any character that is not a digit or a period.
    cleaned = ''.join(ch for ch in amount if ch.isdigit() or ch == '.')
    try:
        return float(cleaned)
    except Exception:
        return 0

def scrape_donors_from_page(url):
    """
    Fetch the page at `url` (using a plain requests.get)
    and parse the "Recent Donors" section.
    Returns a list of (name, amount) tuples.
    (This method is used as a fallback for static pages.)
    """
    response = requests.get(url)
    response.raise_for_status()  # Raise an error if the request fails

    soup = BeautifulSoup(response.text, 'html.parser')

    recent_donors_section = soup.select_one('#profile-recent-donors')
    if not recent_donors_section:
        print("No recent donors section found on page.")
        return []

    donor_entries = recent_donors_section.select('.donor-listing.mb-2')
    donors = []
    for entry in donor_entries:
        name_div = entry.select_one('.text-xl')
        name = name_div.get_text(strip=True) if name_div else None

        amount_div = entry.select_one('.gg-branding-supporting.text-xl')
        amount = amount_div.get_text(strip=True) if amount_div else None

        donors.append((name, amount))
    return donors

def _extract_donor_names(soup):
    """
    Pull donor names from a variety of likely GiveCampus selectors.
    """
    selectors = [
        '#recent_donors_block .profile_block.small .profile_block-content span',
        '.donor-listing .text-xl',
        '.donor-listing .donor-name',
        '.donor .name',
        '.donor-name',
        '.donor_name',
        '.campaign-donor .name',
        '.profile_block-content span',
    ]
    names = []
    seen = set()

    def _add_name(raw):
        name = raw.strip() if raw else ""
        if name and name not in seen:
            names.append(name)
            seen.add(name)

    for sel in selectors:
        for node in soup.select(sel):
            _add_name(node.get_text(strip=True))

    # Handle the "View All Donors" modal table (#all-table) structure.
    for row in soup.select("table#all-table tr.leaderboard-row"):
        first_col = row.find("td")
        if not first_col:
            continue
        # The first col-sm-6 div holds the donor name; the second holds affiliation icons/text.
        name_div = first_col.find("div", class_="col-sm-6")
        if name_div:
            _add_name(name_div.get_text(" ", strip=True))
            continue
        # Fallback: best-effort text grab from the cell.
        _add_name(first_col.get_text(" ", strip=True))
    return names


def _load_local_donors(file_candidates):
    """
    Load donor names from cached local HTML files (e.g., previously downloaded GiveCampus pages).
    Returns a deduped list of names.
    """
    collected = []
    for path_str in file_candidates:
        if not path_str:
            continue
        path = Path(path_str)
        if not path.exists():
            continue
        try:
            soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
            collected.extend(_extract_donor_names(soup))
        except Exception as exc:
            print(f"Warning: failed to load donors from {path}: {exc}")
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for name in collected:
        if name and name not in seen:
            deduped.append(name)
            seen.add(name)
    return deduped


def _cache_response(text, path_value):
    """
    Save fetched HTML to disk so we can re-use it when scraping fails.
    """
    if not path_value:
        return
    try:
        Path(path_value).write_text(text, encoding="utf-8")
    except Exception as exc:
        print(f"Warning: failed to cache response to {path_value}: {exc}")


def _build_http_client():
    """
    Build a requests session with optional User-Agent and cookies
    to help bypass basic bot checks (e.g., Cloudflare).
    """
    session = requests.Session()
    ua = os.getenv("SCRAPE_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36")
    session.headers.update(
        {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    # Optional cookie helpers: set CF clearance or arbitrary cookie string.
    cf_clearance = os.getenv("CF_CLEARANCE_COOKIE")
    cookie_string = os.getenv("SCRAPE_COOKIE_STRING")
    if cf_clearance:
        session.cookies.set("cf_clearance", cf_clearance, domain=".give.njit.edu")
    if cookie_string:
        # Expect "k1=v1; k2=v2" format
        for part in cookie_string.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                session.cookies.set(k, v, domain=".give.njit.edu")
    return session


def _find_campaign_id(soup):
    # Look for modal IDs like myModal12345_all
    modal = soup.find(id=re.compile(r"myModal(\d+)_all"))
    if modal and modal.get("id"):
        m = re.search(r"myModal(\d+)_all", modal["id"])
        if m:
            return m.group(1)
    # Fallback: anchors pointing to campaign_donors.html
    for a in soup.find_all("a", href=True):
        m = re.search(r"/campaigns/(\d+)/campaign_donors\.html", a["href"])
        if m:
            return m.group(1)
    return None


def scrape_givecampus_recent_donors(url):
    """
    Scrape donor names from a GiveCampus campaign page (no amounts required).
    Also tries the "View All Donors" modal URL if present.
    """
    session = _build_http_client()
    response = session.get(url, timeout=15)
    response.raise_for_status()

    _cache_response(response.text, os.getenv("DONOR_CACHE_MAIN_FILE", "honors-winter-gala.html"))

    soup = BeautifulSoup(response.text, 'html.parser')
    donors = _extract_donor_names(soup)

    # Try the campaign's "all donors" modal endpoint if we can find the campaign ID.
    campaign_id = _find_campaign_id(soup)
    if campaign_id:
        modal_url = f"https://give.njit.edu/campaigns/{campaign_id}/campaign_donors.html?show=all"
        try:
            modal_resp = session.get(modal_url, timeout=15)
            modal_resp.raise_for_status()
            _cache_response(modal_resp.text, os.getenv("DONOR_CACHE_MODAL_FILE", "campaign_donors_72810_all.html"))
            modal_soup = BeautifulSoup(modal_resp.text, 'html.parser')
            donors.extend(_extract_donor_names(modal_soup))
        except Exception:
            pass

    # Deduplicate while preserving order.
    deduped = []
    seen = set()
    for name in donors:
        if name not in seen:
            deduped.append(name)
            seen.add(name)

    return [(name, None) for name in deduped]


#############################
# Flask Routes
#############################

@donor_wall_bp.route('/donor-wall')
def donor_wall():
    """
    Normal mode: show nav, normal alignment.
    """
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT name, amount FROM donors')
        donors = c.fetchall()

        c.execute('''
            SELECT scroll_direction, scroll_speed, scroll_position, scroll_width, scroll_height 
            FROM settings WHERE id = 1
        ''')
        row = c.fetchone()
        if row:
            (scroll_direction, scroll_speed, scroll_position, scroll_width, scroll_height) = row
        else:
            scroll_direction, scroll_speed, scroll_position, scroll_width, scroll_height = ('up', 50, 'center', 300, 500)

    return render_template('donor_wall.html',
                           donors=donors,
                           hide_nav=False,
                           display_mode=False,
                           scroll_speed=scroll_speed,
                           scroll_direction=scroll_direction,
                           scroll_position=scroll_position,
                           scroll_width=scroll_width,
                           scroll_height=scroll_height)

@donor_wall_bp.route('/donor-wall-display')
def donor_wall_display():
    """
    Display mode: no nav, center screen.
    """
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT name, amount FROM donors')
        donors = c.fetchall()

        c.execute('''
            SELECT scroll_direction, scroll_speed, scroll_position, scroll_width, scroll_height 
            FROM settings WHERE id = 1
        ''')
        row = c.fetchone()
        if row:
            (scroll_direction, scroll_speed, scroll_position, scroll_width, scroll_height) = row
        else:
            scroll_direction, scroll_speed, scroll_position, scroll_width, scroll_height = ('up', 50, 'center', 300, 500)

    return render_template('donor_wall.html',
                           donors=donors,
                           hide_nav=True,
                           display_mode=True,
                           scroll_speed=scroll_speed,
                           scroll_direction=scroll_direction,
                           scroll_position=scroll_position,
                           scroll_width=scroll_width,
                           scroll_height=scroll_height)

@donor_wall_bp.route('/donor-wall-styles.css')
def donor_wall_styles():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT background_image, font_color, scroll_direction, font_size, 
                   scroll_speed, scroll_position, scroll_width, scroll_height 
            FROM settings WHERE id = 1
        ''')
        row = c.fetchone()

    defaults = ('default.jpg', '#FFFFFF', 'up', 24, 50, 'center', 300, 500)
    if row:
        background_image = row[0] if row[0] else defaults[0]
        font_color = row[1] if row[1] else defaults[1]
        scroll_direction = row[2] if row[2] else defaults[2]
        font_size = row[3] if row[3] else defaults[3]
        scroll_speed = row[4] if row[4] else defaults[4]
        scroll_position = row[5] if row[5] else defaults[5]
        scroll_width = row[6] if row[6] else defaults[6]
        scroll_height = row[7] if row[7] else defaults[7]
    else:
        background_image, font_color, scroll_direction, font_size, scroll_speed, scroll_position, scroll_width, scroll_height = defaults

    position_styles = {
        'top': 'top: 0; left: 50%; transform: translateX(-50%);',
        'center': 'top: 50%; left: 50%; transform: translate(-50%, -50%);',
        'bottom': 'bottom: 0; left: 50%; transform: translateX(-50%);',
        'left': 'top: 50%; left: 0; transform: translateY(-50%);',
        'right': 'top: 50%; right: 0; transform: translateY(-50%);',
    }
    position_style = position_styles.get(scroll_position, position_styles['center'])
    flex_direction = 'column' if scroll_direction in ['up', 'down'] else 'row'
    if scroll_direction in ['left', 'right']:
        mask_gradient = "linear-gradient(to right, transparent 0%, black 18%, black 82%, transparent 100%)"
        donor_item_margin = "0 10px"
    else:
        mask_gradient = "linear-gradient(to bottom, transparent 0%, black 18%, black 82%, transparent 100%)"
        donor_item_margin = "50px 0"

    css = f"""
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@200;700&display=swap');

    html, body {{
      margin: 0;
      padding: 0;
      height: 100%;
      font-family: 'Poppins', sans-serif;
      color: {font_color};
    }}

    body {{
      background: url('/static/uploads/{background_image}') no-repeat center center fixed;
      background-size: cover;
    }}

    .scroll-container {{
      position: absolute;
      {position_style}
      width: {scroll_width}px;
      height: {scroll_height}px;
      overflow: hidden;
      display: flex;
      justify-content: center;
      align-items: center;
      mask-image: {mask_gradient};
      mask-size: 100% 100%;
      mask-repeat: no-repeat;
      -webkit-mask-image: {mask_gradient};
      -webkit-mask-size: 100% 100%;
      -webkit-mask-repeat: no-repeat;
    }}

    .scroll-wrapper {{
      display: flex;
      flex-direction: {flex_direction};
      width: 100%; height: 100%;
      animation: scrollY var(--scroll-duration, 30s) linear infinite;
      animation-play-state: paused;
      animation-direction: normal;
      opacity: 0;
      transition: opacity 0.8s ease;
    }}

    .donor-list {{
      display: flex;
      flex-direction: {flex_direction};
      width: 100%;
      text-align: center;
      font-size: {font_size}px;
      position: relative;
      will-change: transform;
      justify-content: center;
      align-items: center;
      padding: var(--fade-padding-y, 60px) var(--fade-padding-x, 40px);
      box-sizing: border-box;
    }}

    .donor-item {{
      font-size: {font_size}px;
      margin: {donor_item_margin};
      text-align: center;
      opacity: 1;
    }}

    .scroll-wrapper.run {{
      animation-play-state: running;
      opacity: 1;
    }}

    .scroll-wrapper.fade-visible {{
      opacity: 1;
    }}

    @keyframes scrollY {{
      from {{ transform: translateY(0); }}
      to   {{ transform: translateY(calc(-1 * var(--scroll-distance, 0px))); }}
    }}

    @keyframes scrollX {{
      from {{ transform: translateX(0); }}
      to   {{ transform: translateX(calc(-1 * var(--scroll-distance, 0px))); }}
    }}

    @keyframes fadeInUp {{
      from {{
        opacity: 0;
        transform: translateY(20px);
      }}
      to {{
        opacity: 1;
        transform: translateY(0);
      }}
    }}
    """
    response = make_response(css)
    response.headers["Content-Type"] = "text/css"
    return response

@donor_wall_bp.route('/api/donors', methods=['GET'])
def get_donors():
    """
    Returns a paginated list of donors in JSON format.
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    offset = (page - 1) * per_page
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT name, amount FROM donors LIMIT ? OFFSET ?', (per_page, offset))
        donors = c.fetchall()
    donor_list = [{'name': donor[0], 'amount': donor[1]} for donor in donors]
    return jsonify(donor_list)

@donor_wall_bp.route('/scrape-donors', methods=['POST'])
def scrape_donors():
    """
    Scrape donor data from the configured GiveCampus donor page.
    Amounts are optional; names alone are accepted.
    """
    # Connect to settings to retrieve the donor data sources
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT donor_website, google_sheet_id FROM settings WHERE id = 1')
        row = c.fetchone()

    donor_website = row[0] if row and row[0] else None

    donors_list = []

    if donor_website:
        try:
            donors_from_web = scrape_givecampus_recent_donors(donor_website)
            donors_list.extend(donors_from_web)
        except Exception as e:
            print("Error scraping from donor website with Selenium:", e)

    # Fallback: local cached HTML files so we can still display donors without live fetch.
    if not donors_list:
        local_candidates = [
            os.getenv("DONOR_LOCAL_MODAL_FILE"),  # highest priority (all donors modal)
            os.getenv("DONOR_LOCAL_FILE"),
            os.getenv("DONOR_CACHE_MODAL_FILE"),
            os.getenv("DONOR_CACHE_MAIN_FILE"),
            "campaign_donors_72810_all.html",     # repo-cached modal by default
            "honors-winter-gala.html",            # repo-cached main page
        ]
        local_names = _load_local_donors(local_candidates)
        donors_list.extend([(name, None) for name in local_names])

    if not donors_list:
        return jsonify({"message": "No donor data found from configured source."}), 400

    # Insert scraped donors into the donors table
    with get_db() as conn:
        c = conn.cursor()
        c.execute('DELETE FROM donors')
        for (name, amount) in donors_list:
            if not name:
                continue
            numeric_amount = parse_amount_to_number(amount)
            c.execute('INSERT INTO donors (name, amount) VALUES (?, ?)', (name, numeric_amount))

    return jsonify({"message": "Donors scraped successfully.", "donors_count": len(donors_list)})

