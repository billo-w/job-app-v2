import os
import requests
from flask import Flask, request, jsonify, render_template, flash
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

# Initialize the Flask application
# template_folder='templates' tells Flask where to look for HTML files
app = Flask(__name__, template_folder='templates')
# Required for flashing messages (like errors) to the user
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'a_default_secret_key_for_dev') # Use env var for production

# Retrieve Adzuna API credentials from environment variables
ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID')
ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY')

# Adzuna API base URL
ADZUNA_API_BASE_URL = 'https://api.adzuna.com/v1/api/jobs'

@app.route('/', methods=['GET'])
def home():
    """
    Renders the main page with the input form.
    """
    # Render the index.html template. Initially, insights will be None.
    return render_template('index.html', insights=None, form_data={})

@app.route('/insights', methods=['POST'])
def get_insights():
    """
    Handles form submission, fetches job insights from Adzuna,
    and re-renders the main page with the results.
    """
    # Get form data
    job_title = request.form.get('what')
    location = request.form.get('where')
    country_code = request.form.get('country')
    form_data = {'what': job_title, 'where': location, 'country': country_code} # Keep form data for re-rendering

    # --- Input Validation ---
    if not all([job_title, location, country_code]):
        flash("Please fill in all fields: Job Title, Location, and Country Code.", "error")
        # Re-render the form, passing back the partially filled data
        return render_template('index.html', insights=None, form_data=form_data)

    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
         flash("API credentials not configured on the server.", "error")
         return render_template('index.html', insights=None, form_data=form_data)

    # --- Prepare API Request ---
    api_url = f"{ADZUNA_API_BASE_URL}/{country_code.lower()}/search/1"
    params = {
        'app_id': ADZUNA_APP_ID,
        'app_key': ADZUNA_APP_KEY,
        'what': job_title,
        'where': location,
        'results_per_page': 10, # Get a few more results for display
        'content-type': 'application/json'
    }

    # --- Make API Call ---
    insights_data = None
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
        data = response.json()

        # --- Extract Insights ---
        total_jobs = data.get('count', 0)
        results = data.get('results', [])
        job_listings = [
            {
                "title": job.get('title'),
                "company": job.get('company', {}).get('display_name', 'N/A'),
                "location": job.get('location', {}).get('display_name', 'N/A'),
                "description": job.get('description', 'No description available.'),
                "url": job.get('redirect_url'),
                "created": job.get('created') # Adzuna provides creation date
            }
            for job in results
        ]

        insights_data = {
            "query": {
                "what": job_title,
                "where": location,
                "country": country_code
            },
            "total_matching_jobs": total_jobs,
            "job_listings": job_listings
        }

    except requests.exceptions.HTTPError as e:
         # Handle specific HTTP errors (like 400 Bad Request if params are wrong)
         error_message = f"Adzuna API Error: {e.response.status_code}. Check your inputs or API key."
         try:
             # Try to get a more specific error from Adzuna's response
             api_error = e.response.json().get('__all__') or e.response.json().get('error')
             if api_error:
                 error_message += f" Details: {api_error}"
         except Exception:
             pass # Ignore if parsing error fails
         flash(error_message, "error")
    except requests.exceptions.RequestException as e:
        # Handle network errors, API errors, etc.
        flash(f"Failed to connect to Adzuna API: {e}", "error")
    except Exception as e:
        # Handle unexpected errors
        app.logger.error(f"An unexpected error occurred: {e}")
        flash("An internal server error occurred.", "error")

    # Re-render the main page, passing the fetched insights (or None if error)
    # Also pass back the original form data to repopulate fields
    return render_template('index.html', insights=insights_data, form_data=form_data)

# --- Main execution ---
if __name__ == '__main__':
    # Runs the development server. Use Gunicorn/Nginx for production.
    app.run(host='0.0.0.0', port=5000, debug=True) # Debug=True is helpful locally