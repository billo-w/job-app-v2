import os
import requests
from flask import Flask, request, jsonify, render_template, flash
from dotenv import load_dotenv
import logging
import json # For safely parsing potential JSON in descriptions

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
RESULTS_PER_PAGE = 20 # Fetch more jobs for display

# --- Azure AI Configuration ---
AZURE_AI_ENDPOINT = os.getenv('AZURE_AI_ENDPOINT')
AZURE_AI_KEY = os.getenv('AZURE_AI_KEY')

def get_salary_histogram(country_code, location, job_title):
    """
    Fetches salary histogram data from Adzuna.

    Args:
        country_code (str): 2-letter country code.
        location (str): Location name.
        job_title (str): Job title/keywords.

    Returns:
        dict: Salary histogram data, or None if an error occurs or no data found.
    """
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        app.logger.warning("Adzuna credentials not set, cannot fetch salary histogram.")
        return None

    histogram_url = f"{ADZUNA_API_BASE_URL}/{country_code.lower()}/histogram"
    params = {
        'app_id': ADZUNA_APP_ID,
        'app_key': ADZUNA_APP_KEY,
        'location0': location, # Adzuna uses location0 for histogram
        'what': job_title,
        'content-type': 'application/json'
    }
    app.logger.info(f"Fetching salary histogram for: {params}")
    try:
        response = requests.get(histogram_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if 'histogram' in data and data['histogram']:
            app.logger.info("Successfully fetched salary histogram.")
            # Calculate average if possible (simple mean, may not be perfect)
            total_salary = 0
            total_count = 0
            for salary_point, count in data['histogram'].items():
                try:
                    total_salary += float(salary_point) * count
                    total_count += count
                except ValueError:
                    continue # Skip if salary point isn't a number
            average_salary = round(total_salary / total_count) if total_count > 0 else None
            return {"histogram": data['histogram'], "average": average_salary}
        else:
            app.logger.info("No salary histogram data found for this query.")
            return None
    except requests.exceptions.Timeout:
        app.logger.error("Request to Adzuna histogram endpoint timed out.")
        # Don't flash here, it's supplementary data
        return None
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error fetching salary histogram: {e}")
        if e.response is not None:
             app.logger.error(f"Histogram Response Status: {e.response.status_code}, Body: {e.response.text[:200]}")
        return None
    except Exception as e:
         app.logger.error(f"Unexpected error fetching salary histogram: {e}")
         return None


def get_ai_summary(query_details, total_jobs, job_listings_sample, salary_data):
    """
    Calls Azure AI model for an enhanced recruiter-focused summary,
    incorporating salary data and inferring skills.

    Args:
        query_details (dict): Contains 'what', 'where', 'country'.
        total_jobs (int): Total number of jobs found.
        job_listings_sample (list): Sample list of job listing dicts (including descriptions).
        salary_data (dict): Dictionary containing salary histogram and average, or None.

    Returns:
        str: The AI-generated summary, or None if an error occurs.
    """
    if not AZURE_AI_ENDPOINT or not AZURE_AI_KEY:
        app.logger.warning("Azure AI Endpoint or Key not configured. Skipping summary.")
        return None

    # --- Prepare data for the prompt ---
    sample_titles = [job['title'] for job in job_listings_sample[:5]]
    # Combine descriptions from the sample for skill inference (limit length)
    sample_descriptions = " ".join([
        job['description'] for job in job_listings_sample[:5]
        if isinstance(job.get('description'), str) # Ensure description is a string
    ])
    # Limit combined description length to avoid overly long prompts
    max_desc_length = 1000
    if len(sample_descriptions) > max_desc_length:
        sample_descriptions = sample_descriptions[:max_desc_length] + "..."

    salary_info = "Not available"
    if salary_data and salary_data.get('average'):
        # Format average salary nicely (basic example, could use locale)
        salary_info = f"approximately {salary_data['average']:,} (currency based on country)"
    elif salary_data and salary_data.get('histogram'):
         salary_info = "Distribution data available, but average could not be calculated."

    # --- Construct the Enhanced Prompt ---
    system_message = (
        "You are an AI assistant providing recruitment market analysis. "
        "Focus on actionable insights for a recruiter based *only* on the provided data."
    )
    user_prompt = (
        f"Analyze the job market for a recruiter hiring for '{query_details['what']}' "
        f"in '{query_details['where']}, {query_details['country'].upper()}'.\n\n"
        f"**Market Data:**\n"
        f"- Total Job Listings Found: {total_jobs}\n"
        f"- Estimated Average Salary: {salary_info}\n"
        f"- Sample Job Titles: {', '.join(sample_titles) if sample_titles else 'N/A'}\n"
        f"- Sample Job Description Excerpts: {sample_descriptions if sample_descriptions else 'N/A'}\n\n"
        f"**Recruiter Analysis (Based *only* on above data):**\n"
        f"1.  **Market Activity & Competitiveness:** Based on job volume and salary data (if available), how active/competitive does this market seem?\n"
        f"2.  **Key Skills/Keywords:** Based *only* on the sample titles and descriptions, what 2-3 potential key skills or technologies seem commonly required?\n"
        f"3.  **Candidate Pool & Sourcing:** What does the job volume suggest about the likely candidate pool size and the potential need for proactive sourcing vs. relying on applications?\n\n"
        f"Provide a concise, bulleted summary. Do not invent skills or salary details not present in the data."
    )

    payload = {
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 250, # Increased slightly for more detailed analysis
        "temperature": 0.5
    }
    headers = {
        'Content-Type': 'application/json',
        'api-key': AZURE_AI_KEY
    }

    app.logger.info(f"Sending enhanced recruiter request to Azure AI Endpoint: {AZURE_AI_ENDPOINT}")
    try:
        response = requests.post(AZURE_AI_ENDPOINT, headers=headers, json=payload, timeout=30) # Increased timeout
        response.raise_for_status()
        response_data = response.json()
        if 'choices' in response_data and len(response_data['choices']) > 0:
            message = response_data['choices'][0].get('message')
            if message and 'content' in message:
                summary = message['content']
                app.logger.info("Successfully received enhanced recruiter summary from Azure AI.")
                return summary.strip()
            else: app.logger.warning(f"Azure AI response 'choices' structure unexpected: {message}"); return None
        else: app.logger.warning(f"Azure AI response did not contain 'choices'. Response: {response_data}"); return None
    except requests.exceptions.Timeout:
        app.logger.error("Request to Azure AI timed out."); flash("Could not generate AI summary: The request timed out.", "warning"); return None
    except requests.exceptions.RequestException as e:
        # Log error details as before...
        app.logger.error(f"Error calling Azure AI endpoint: {e}")
        error_details = ""
        if e.response is not None:
            try: error_details = e.response.text
            except Exception: pass
            try:
                error_json = e.response.json();
                if 'error' in error_json: app.logger.error(f"Azure AI Error Code: {error_json['error'].get('code')}, Message: {error_json['error'].get('message')}")
            except Exception: pass
            app.logger.error(f"Azure AI Raw Response Status: {e.response.status_code}, Body: {error_details[:500]}")
        flash(f"Could not generate AI summary: Error communicating with the AI service (Status: {e.response.status_code if e.response is not None else 'N/A'}). Please check configuration.", "warning")
        return None
    except Exception as e:
        app.logger.error(f"Unexpected error during AI summary generation: {e}"); flash("An unexpected error occurred while generating the AI summary.", "warning"); return None


@app.route('/', methods=['GET'])
def home():
    """ Renders the main page with the input form. """
    return render_template('index.html', insights=None, form_data={})

@app.route('/insights', methods=['POST'])
def get_insights():
    """
    Handles form submission, fetches job insights & salary data from Adzuna,
    gets enhanced AI summary, and re-renders the main page.
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
    ai_summary = None

    # --- Call Adzuna Search API ---
    api_url = f"{ADZUNA_API_BASE_URL}/{country_code.lower()}/search/1"
    params = {
        'app_id': ADZUNA_APP_ID, 'app_key': ADZUNA_APP_KEY, 'what': job_title,
        'where': location, 'results_per_page': RESULTS_PER_PAGE,
        'content-type': 'application/json'
    }
    try:
        app.logger.info(f"Fetching Adzuna data for: {params}")
        response = requests.get(api_url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        app.logger.info("Successfully fetched data from Adzuna.")

        total_jobs = data.get('count', 0)
        results = data.get('results', [])
        job_listings = [
            { "title": job.get('title'), "company": job.get('company', {}).get('display_name', 'N/A'),
              "location": job.get('location', {}).get('display_name', 'N/A'),
              "description": job.get('description', 'No description available.'),
              "url": job.get('redirect_url'), "created": job.get('created') }
            for job in results
        ]

        insights_data = {
            "query": form_data, "total_matching_jobs": total_jobs,
            "job_listings": job_listings, "ai_summary": None, "salary_data": None
        }

        # --- Call Adzuna Histogram API (if search successful) ---
        if insights_data:
            salary_data = get_salary_histogram(country_code, location, job_title)
            if salary_data:
                insights_data['salary_data'] = salary_data # Add salary data to insights

        # --- Call Azure AI for Summary (if search successful) ---
        if insights_data:
            ai_summary = get_ai_summary(
                insights_data['query'], insights_data['total_matching_jobs'],
                insights_data['job_listings'][:10], # Pass sample listings (with descriptions)
                salary_data # Pass fetched salary data
            )
            if ai_summary:
                insights_data['ai_summary'] = ai_summary

    except requests.exceptions.Timeout:
         app.logger.error("Request to Adzuna search timed out.")
         flash("Could not retrieve job data: The request to Adzuna timed out.", "error")
    except requests.exceptions.HTTPError as e:
         # Log error details as before...
         error_message = f"Adzuna API Error: {e.response.status_code}."
         try: api_error_details = e.response.json().get('__all__') or e.response.json().get('error') or e.response.text; error_message += f" Details: {str(api_error_details)[:200]}"
         except Exception: pass
         app.logger.error(f"Adzuna HTTP Error: {error_message}"); flash(error_message, "error")
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Failed to connect to Adzuna API: {e}"); flash(f"Could not retrieve job data: Failed to connect to Adzuna API.", "error")
    except Exception as e:
        app.logger.error(f"Unexpected error during Adzuna data fetch: {e}"); flash("An internal server error occurred while retrieving job data.", "error")

    # --- Render Template ---
    return render_template('index.html', insights=insights_data, form_data=form_data)


# --- Main execution ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)