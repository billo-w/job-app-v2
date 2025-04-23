import os
import requests
from flask import Flask, request, jsonify, render_template, flash
from dotenv import load_dotenv
import logging
import json
import markdown # Import the markdown library
from markupsafe import Markup # Import Markup for safe HTML rendering

# Configure basic logging
logging.basicConfig(level=logging.INFO)

# Load environment variables
load_dotenv()

# Initialize Flask App
app = Flask(__name__, template_folder='templates')
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'a_default_secret_key_for_dev')

# --- Adzuna Configuration ---
ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID')
ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY')
ADZUNA_API_BASE_URL = 'https://api.adzuna.com/v1/api/jobs'
RESULTS_PER_PAGE = 100

# --- Azure AI Configuration ---
AZURE_AI_ENDPOINT = os.getenv('AZURE_AI_ENDPOINT')
AZURE_AI_KEY = os.getenv('AZURE_AI_KEY')

def get_salary_histogram(country_code, location, job_title):
    """ Fetches salary histogram data from Adzuna. (No changes needed here) """
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        app.logger.warning("Adzuna credentials not set, cannot fetch salary histogram.")
        return None
    histogram_url = f"{ADZUNA_API_BASE_URL}/{country_code.lower()}/histogram"
    params = { 'app_id': ADZUNA_APP_ID, 'app_key': ADZUNA_APP_KEY, 'location0': location, 'what': job_title, 'content-type': 'application/json' }
    app.logger.info(f"Fetching salary histogram for: {params}")
    try:
        response = requests.get(histogram_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if 'histogram' in data and data['histogram']:
            app.logger.info("Successfully fetched salary histogram.")
            total_salary = 0; total_count = 0
            for salary_point, count in data['histogram'].items():
                try: total_salary += float(salary_point) * count; total_count += count
                except ValueError: continue
            average_salary = round(total_salary / total_count) if total_count > 0 else None
            return {"histogram": data['histogram'], "average": average_salary}
        else: app.logger.info("No salary histogram data found."); return None
    except requests.exceptions.Timeout: app.logger.error("Histogram request timed out."); return None
    except requests.exceptions.RequestException as e: app.logger.error(f"Error fetching salary histogram: {e}"); return None
    except Exception as e: app.logger.error(f"Unexpected error fetching salary histogram: {e}"); return None


def get_ai_summary(query_details, total_jobs, job_listings_sample, salary_data):
    """ Calls Azure AI model for an enhanced recruiter-focused summary. (No changes needed here) """
    if not AZURE_AI_ENDPOINT or not AZURE_AI_KEY:
        app.logger.warning("Azure AI Endpoint or Key not configured. Skipping summary.")
        return None
    # --- Prepare data for the prompt ---
    sample_titles = [job['title'] for job in job_listings_sample[:7]]
    sample_descriptions = " ".join([job['description'] for job in job_listings_sample[:5] if isinstance(job.get('description'), str)])
    max_desc_length = 1000
    if len(sample_descriptions) > max_desc_length: sample_descriptions = sample_descriptions[:max_desc_length] + "..."
    salary_info = "Not available"
    if salary_data and salary_data.get('average'): salary_info = f"approximately {salary_data['average']:,} (currency based on country)"
    elif salary_data and salary_data.get('histogram'): salary_info = "Distribution data available, but average could not be calculated."
    # --- Construct the Enhanced Prompt ---
    system_message = ("You are an AI assistant providing recruitment market analysis. Focus on actionable insights for a recruiter based *only* on the provided data. Use Markdown for formatting (like **bold**).") # Added hint to use Markdown
    user_prompt = (
        f"Analyze the job market for a recruiter hiring for '{query_details['what']}' in '{query_details['where']}, {query_details['country'].upper()}'.\n\n"
        f"**Market Data:**\n- Total Job Listings Found: {total_jobs}\n- Estimated Average Salary: {salary_info}\n- Sample Job Titles: {', '.join(sample_titles) if sample_titles else 'N/A'}\n- Sample Job Description Excerpts: {sample_descriptions if sample_descriptions else 'N/A'}\n\n"
        f"**Recruiter Analysis (Based *only* on above data - use Markdown for emphasis):**\n1.  **Market Activity & Competitiveness:** Based on job volume and salary data (if available), how active/competitive does this market seem?\n2.  **Key Skills/Keywords:** Based *only* on the sample titles and descriptions, what 2-3 potential key skills or technologies seem commonly required?\n3.  **Candidate Pool & Sourcing:** What does the job volume suggest about the likely candidate pool size and the potential need for proactive sourcing vs. relying on applications?\n\nProvide a concise, bulleted summary. Do not invent skills or salary details not present in the data."
    )
    payload = { "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": user_prompt}], "max_tokens": 250, "temperature": 0.5 }
    headers = { 'Content-Type': 'application/json', 'api-key': AZURE_AI_KEY }
    app.logger.info(f"Sending enhanced recruiter request to Azure AI Endpoint: {AZURE_AI_ENDPOINT}")
    try:
        response = requests.post(AZURE_AI_ENDPOINT, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        response_data = response.json()
        if 'choices' in response_data and len(response_data['choices']) > 0:
            message = response_data['choices'][0].get('message')
            if message and 'content' in message:
                summary = message['content']
                app.logger.info("Successfully received enhanced recruiter summary from Azure AI.")
                return summary.strip() # Return raw summary text
            else: app.logger.warning(f"Azure AI response 'choices' structure unexpected: {message}"); return None
        else: app.logger.warning(f"Azure AI response did not contain 'choices'. Response: {response_data}"); return None
    except requests.exceptions.Timeout: app.logger.error("Request to Azure AI timed out."); flash("Could not generate AI summary: The request timed out.", "warning"); return None
    except requests.exceptions.RequestException as e: app.logger.error(f"Error calling Azure AI endpoint: {e}"); flash(f"Could not generate AI summary: Error communicating with the AI service.", "warning"); return None
    except Exception as e: app.logger.error(f"Unexpected error during AI summary generation: {e}"); flash("An unexpected error occurred while generating the AI summary.", "warning"); return None


@app.route('/', methods=['GET'])
def home():
    """ Renders the main page with the input form. """
    return render_template('index.html', insights=None, form_data={})

@app.route('/insights', methods=['POST'])
def get_insights():
    """
    Handles form submission, fetches job insights & salary data from Adzuna,
    gets enhanced AI summary, converts summary to HTML, and re-renders the main page.
    """
    job_title = request.form.get('what')
    location = request.form.get('where')
    country_code = request.form.get('country')
    form_data = {'what': job_title, 'where': location, 'country': country_code}

    if not all([job_title, location, country_code]):
        flash("Please fill in all fields: Job Title, Location, and Country Code.", "error")
        return render_template('index.html', insights=None, form_data=form_data)

    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
         flash("Adzuna API credentials not configured on the server.", "error")
         return render_template('index.html', insights=None, form_data=form_data)

    insights_data = None
    salary_data = None
    ai_summary_raw = None # Store the raw summary text

    # --- Call Adzuna Search API ---
    api_url = f"{ADZUNA_API_BASE_URL}/{country_code.lower()}/search/1"
    params = { 'app_id': ADZUNA_APP_ID, 'app_key': ADZUNA_APP_KEY, 'what': job_title, 'where': location, 'results_per_page': RESULTS_PER_PAGE, 'content-type': 'application/json' }
    try:
        app.logger.info(f"Fetching Adzuna data for: {params}")
        response = requests.get(api_url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        app.logger.info("Successfully fetched data from Adzuna.")

        total_jobs = data.get('count', 0)
        results = data.get('results', [])
        job_listings = [ { "title": job.get('title'), "company": job.get('company', {}).get('display_name', 'N/A'), "location": job.get('location', {}).get('display_name', 'N/A'), "description": job.get('description', 'No description available.'), "url": job.get('redirect_url'), "created": job.get('created') } for job in results ]

        insights_data = {
            "query": form_data, "total_matching_jobs": total_jobs,
            "job_listings": job_listings,
            "ai_summary_html": None, # Initialize HTML version as None
            "salary_data": None
        }

        # --- Call Adzuna Histogram API (if search successful) ---
        if insights_data:
            salary_data = get_salary_histogram(country_code, location, job_title)
            if salary_data: insights_data['salary_data'] = salary_data

        # --- Call Azure AI for Summary (if search successful) ---
        if insights_data:
            ai_summary_raw = get_ai_summary( insights_data['query'], insights_data['total_matching_jobs'], insights_data['job_listings'][:10], salary_data )

            # --- Convert AI Summary Markdown to HTML ---
            if ai_summary_raw:
                # Convert Markdown to HTML
                # Using 'fenced_code' extension allows for potential code blocks if needed later
                html_summary = markdown.markdown(ai_summary_raw, extensions=['fenced_code'])
                # Mark the HTML as safe for Jinja rendering
                # Note: This assumes you trust the output from the Azure AI model.
                # If the model could generate malicious HTML/JS, this would be a security risk.
                insights_data['ai_summary_html'] = Markup(html_summary)
                app.logger.info("Converted AI summary Markdown to HTML.")

    except requests.exceptions.Timeout: app.logger.error("Adzuna search timed out."); flash("Could not retrieve job data: Timed out.", "error")
    except requests.exceptions.HTTPError as e: error_message = f"Adzuna API Error: {e.response.status_code}."; flash(error_message, "error") # Simplified flash
    except requests.exceptions.RequestException as e: app.logger.error(f"Adzuna connection error: {e}"); flash(f"Could not retrieve job data: Connection error.", "error")
    except Exception as e: app.logger.error(f"Unexpected error during data fetch: {e}"); flash("An internal server error occurred.", "error")

    # --- Render Template ---
    return render_template('index.html', insights=insights_data, form_data=form_data)


# --- Main execution ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)