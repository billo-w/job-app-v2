import os
import requests
from flask import Flask, request, jsonify, render_template, flash
from dotenv import load_dotenv
import logging

# Configure basic logging
logging.basicConfig(level=logging.INFO)

# Load environment variables from a .env file
load_dotenv()

# Initialize the Flask application
app = Flask(__name__, template_folder='templates')
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'a_default_secret_key_for_dev')

# --- Adzuna Configuration ---
ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID')
ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY')
ADZUNA_API_BASE_URL = 'https://api.adzuna.com/v1/api/jobs'

# --- Azure AI Foundry Configuration ---
# IMPORTANT: This should be the FULL endpoint URL including deployment name and api-version
# e.g., https://<resourcename>.openai.azure.com/openai/deployments/<deploymentname>/chat/completions?api-version=YYYY-MM-DD
AZURE_AI_ENDPOINT = os.getenv('AZURE_AI_ENDPOINT')
AZURE_AI_KEY = os.getenv('AZURE_AI_KEY')

def get_ai_summary(query_details, total_jobs, job_listings_sample):
    """
    Calls the deployed Azure AI (OpenAI compatible) model to generate a job market summary.

    Args:
        query_details (dict): Contains 'what', 'where', 'country'.
        total_jobs (int): The total number of jobs found by Adzuna.
        job_listings_sample (list): A sample list of job listing dicts.

    Returns:
        str: The AI-generated summary, or None if an error occurs.
    """
    if not AZURE_AI_ENDPOINT or not AZURE_AI_KEY:
        app.logger.warning("Azure AI Endpoint or Key not configured. Skipping summary.")
        return None

    # --- Prepare the prompt for the AI model (Chat Completions format) ---
    sample_titles = [job['title'] for job in job_listings_sample[:5]] # Use top 5 titles

    system_message = "You are an AI assistant providing brief job market summaries."
    user_prompt = (
        f"Summarize the current job market based on the following data for '{query_details['what']}' jobs "
        f"in '{query_details['where']}, {query_details['country'].upper()}'.\n\n"
        f"Total matching jobs found: {total_jobs}\n"
        f"Sample job titles found: {', '.join(sample_titles) if sample_titles else 'None available'}\n\n"
        f"Provide a concise (2-3 sentences) overview of the market activity and demand for this role in this location. Focus on whether the market seems active or quiet."
    )

    # --- Prepare the request payload for Azure OpenAI Chat Completions ---
    payload = {
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 100,
        "temperature": 0.6 # Slightly lower temp for more factual summary
    }

    # --- Prepare Headers for Azure OpenAI ---
    headers = {
        'Content-Type': 'application/json',
        'api-key': AZURE_AI_KEY # Use 'api-key' header for Azure OpenAI
    }

    app.logger.info(f"Sending request to Azure AI Endpoint: {AZURE_AI_ENDPOINT}")
    try:
        # Use the full endpoint URL provided in the environment variable
        response = requests.post(AZURE_AI_ENDPOINT, headers=headers, json=payload, timeout=25) # Increased timeout slightly
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        # --- Extract Summary from Chat Completions Response ---
        response_data = response.json()

        # Standard path for chat completions response content
        if 'choices' in response_data and len(response_data['choices']) > 0:
            message = response_data['choices'][0].get('message')
            if message and 'content' in message:
                summary = message['content']
                app.logger.info("Successfully received summary from Azure AI.")
                return summary.strip()
            else:
                 app.logger.warning(f"Azure AI response 'choices' structure unexpected: {message}")
                 return None
        else:
            app.logger.warning(f"Azure AI response did not contain expected 'choices' field. Response: {response_data}")
            return None

    except requests.exceptions.Timeout:
        app.logger.error("Request to Azure AI timed out.")
        flash("Could not generate AI summary: The request timed out.", "warning")
        return None
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error calling Azure AI endpoint: {e}")
        error_details = ""
        if e.response is not None:
            try:
                error_details = e.response.text
            except Exception: pass
            # Log specific Azure error if available
            try:
                error_json = e.response.json()
                if 'error' in error_json:
                    app.logger.error(f"Azure AI Error Code: {error_json['error'].get('code')}, Message: {error_json['error'].get('message')}")
            except Exception: pass # Ignore if response isn't JSON or doesn't have 'error'
            app.logger.error(f"Azure AI Raw Response Status: {e.response.status_code}, Body: {error_details[:500]}")
        flash(f"Could not generate AI summary: Error communicating with the AI service (Status: {e.response.status_code if e.response is not None else 'N/A'}). Please check configuration.", "warning")
        return None
    except Exception as e:
        app.logger.error(f"Unexpected error during AI summary generation: {e}")
        flash("An unexpected error occurred while generating the AI summary.", "warning")
        return None


@app.route('/', methods=['GET'])
def home():
    """ Renders the main page with the input form. """
    return render_template('index.html', insights=None, form_data={})

@app.route('/insights', methods=['POST'])
def get_insights():
    """
    Handles form submission, fetches job insights from Adzuna, gets AI summary,
    and re-renders the main page with the results.
    """
    job_title = request.form.get('what')
    location = request.form.get('where')
    country_code = request.form.get('country')
    form_data = {'what': job_title, 'where': location, 'country': country_code}

    # --- Input Validation ---
    if not all([job_title, location, country_code]):
        flash("Please fill in all fields: Job Title, Location, and Country Code.", "error")
        return render_template('index.html', insights=None, form_data=form_data)

    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
         flash("Adzuna API credentials not configured on the server. Please contact the administrator.", "error")
         return render_template('index.html', insights=None, form_data=form_data)

    # --- Prepare Adzuna API Request ---
    api_url = f"{ADZUNA_API_BASE_URL}/{country_code.lower()}/search/1"
    params = {
        'app_id': ADZUNA_APP_ID,
        'app_key': ADZUNA_APP_KEY,
        'what': job_title,
        'where': location,
        'results_per_page': 10,
        'content-type': 'application/json'
    }

    insights_data = None
    ai_summary = None # Initialize AI summary

    # --- Call Adzuna API ---
    try:
        app.logger.info(f"Fetching Adzuna data for: {params}")
        response = requests.get(api_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        app.logger.info("Successfully fetched data from Adzuna.")

        # --- Extract Adzuna Insights ---
        total_jobs = data.get('count', 0)
        results = data.get('results', [])
        job_listings = [
            {
                "title": job.get('title'),
                "company": job.get('company', {}).get('display_name', 'N/A'),
                "location": job.get('location', {}).get('display_name', 'N/A'),
                "description": job.get('description', 'No description available.'),
                "url": job.get('redirect_url'),
                "created": job.get('created')
            }
            for job in results
        ]

        insights_data = {
            "query": { "what": job_title, "where": location, "country": country_code },
            "total_matching_jobs": total_jobs,
            "job_listings": job_listings,
            "ai_summary": None # Placeholder for AI summary
        }

        # --- Call Azure AI for Summary (if Adzuna call was successful) ---
        if insights_data:
            ai_summary = get_ai_summary(insights_data['query'], insights_data['total_matching_jobs'], insights_data['job_listings'])
            if ai_summary:
                insights_data['ai_summary'] = ai_summary # Add summary to insights if successful

    except requests.exceptions.Timeout:
         app.logger.error("Request to Adzuna timed out.")
         flash("Could not retrieve job data: The request to Adzuna timed out.", "error")
    except requests.exceptions.HTTPError as e:
         error_message = f"Adzuna API Error: {e.response.status_code}."
         try:
             api_error_details = e.response.json().get('__all__') or e.response.json().get('error') or e.response.text
             if api_error_details:
                 error_message += f" Details: {str(api_error_details)[:200]}"
         except Exception: pass
         app.logger.error(f"Adzuna HTTP Error: {error_message}")
         flash(error_message, "error")
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Failed to connect to Adzuna API: {e}")
        flash(f"Could not retrieve job data: Failed to connect to Adzuna API.", "error")
    except Exception as e:
        app.logger.error(f"Unexpected error during Adzuna data fetch: {e}")
        flash("An internal server error occurred while retrieving job data.", "error")

    # --- Render Template ---
    return render_template('index.html', insights=insights_data, form_data=form_data)


# --- Main execution ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)