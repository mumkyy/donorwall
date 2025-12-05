# main.py
import os
import math

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, redirect, url_for
import requests

from db import init_db
from auth.routes import auth_bp
from admin.routes import admin_bp
from donor.routes import donor_wall_bp

# Load environment variables from a local .env file if present.
load_dotenv()

def schedule_scrape(app):
    """
    Schedule a job that triggers donor scraping on an interval.
    This function uses the requests library to send a POST request to the /scrape-donors endpoint.
    """
    with app.app_context():
        def trigger_scrape():
            try:
                scrape_url = os.getenv("SCRAPE_TRIGGER_URL", "http://localhost:5000/scrape-donors")
                response = requests.post(scrape_url)
                result = response.json()
                # Log the result to Flask's logger:
                app.logger.info("Scrape triggered successfully. Response: %s", result)
                # Also print a message to the console:
                print("Donor scraping completed:")
                print("  Message:", result.get("message", "No message"))
                print("  Donors scraped count:", result.get("donors_count", "Unknown"))
            except Exception as e:
                app.logger.error("Error triggering scrape: %s", e)
                print("Error during donor scraping:", e)

        scheduler = BackgroundScheduler()
        try:
            interval_minutes = float(os.getenv("SCRAPE_INTERVAL_MINUTES", "15"))
        except ValueError:
            interval_minutes = 15.0
        if interval_minutes <= 0:
            interval_minutes = 15.0

        # APScheduler interval trigger accepts seconds; compute once to allow sub-minute intervals.
        # Clamp to a sensible floor to avoid log spam and over-scraping.
        interval_seconds = max(math.ceil(interval_minutes * 60), 30)
        scheduler.add_job(trigger_scrape, 'interval', seconds=interval_seconds)
        scheduler.start()
        app.scheduler = scheduler  # Optional: store scheduler on app

def create_app():
    app = Flask(__name__)
    # Use a stable secret key sourced from the environment (set FLASK_SECRET_KEY in .env).
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-me")

    init_db()  # Ensure DB schema is set

    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(donor_wall_bp)
    # The donor_wall routes have no prefix, so /donor-wall, /donor-wall-display, etc.

    @app.route('/')
    def home():
        return redirect(url_for('donor_wall.donor_wall'))

    # Start the scraping scheduler if enabled (default: enabled)
    if os.getenv("ENABLE_SCHEDULER", "true").lower() == "true":
        schedule_scrape(app)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', debug=True)

