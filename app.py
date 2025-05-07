import os
import requests
import json
import time
from flask import (Flask, request, jsonify, render_template, flash, redirect,
                   url_for, session)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import (LoginManager, UserMixin, login_user, logout_user,
                         login_required, current_user)
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect, generate_csrf
from wtforms import StringField, PasswordField, SubmitField, BooleanField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import logging
import markdown
from markupsafe import Markup
from urllib.parse import urlparse, parse_qs

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)
logger.info("--- app.py loaded ---")
load_dotenv() # Load environment variables early

# --- Extensions Initialization (outside factory) ---
logger.info("--- Initializing extensions (globally) ---")
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
logger.info("--- Extensions initialized ---")

# --- API Configuration (Constants) ---
ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID')
ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY')
ADZUNA_API_BASE_URL = 'https://api.adzuna.com/v1/api/jobs'
RESULTS_PER_PAGE = 20
AZURE_AI_ENDPOINT = os.getenv('AZURE_AI_ENDPOINT')
AZURE_AI_KEY = os.getenv('AZURE_AI_KEY')

# --- Database Models ---
logger.info("--- Defining models ---")
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    saved_jobs = db.relationship('SavedJob', backref='user', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.email}>'

class SavedJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    adzuna_job_id = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    company = db.Column(db.String(150))
    location = db.Column(db.String(150))
    adzuna_url = db.Column(db.String(500))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'adzuna_job_id', name='_user_job_uc'),)

    def __repr__(self):
        return f'<SavedJob {self.title} ({self.adzuna_job_id})>'
logger.info("--- Models defined ---")

# --- Forms (using Flask-WTF) ---
logger.info("--- Defining forms ---")
class RegistrationForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password', message='Passwords must match.')])
    submit = SubmitField('Register')

    def validate_email(self, email):
        try:
            user = User.query.filter_by(email=email.data).first()
            if user:
                raise ValidationError('That email is already taken. Please choose a different one or login.')
        except Exception as e:
            logger.warning(f"Could not perform User query during form definition: {e}")


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')
logger.info("--- Forms defined ---")

# --- Application Factory Function ---
def create_app(config_object=None):
    """Creates and configures the Flask application."""
    logger.info("--- ENTERING create_app() ---")
    app = Flask(__name__, instance_relative_config=False, template_folder='templates')
    logger.info("--- Flask app instance created ---")

    # --- Load Configuration ---
    logger.info("--- Loading configuration ---")
    app.config.update(
        SECRET_KEY=os.getenv('FLASK_SECRET_KEY', 'default-dev-secret-key'),
        SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ECHO=os.getenv('SQLALCHEMY_ECHO', 'False').lower() in ('true', '1', 't'),
        WTF_CSRF_ENABLED=True
    )
    logger.info(f"Default DATABASE_URL from env: {app.config.get('SQLALCHEMY_DATABASE_URI')}")

    if config_object:
        app.config.from_object(config_object)
        logger.info(f"Applied config object: {config_object}")

    runtime_db_uri = os.getenv('SQLALCHEMY_DATABASE_URI')
    if runtime_db_uri:
         app.config['SQLALCHEMY_DATABASE_URI'] = runtime_db_uri
         logger.info(f"Overriding DB URI with runtime env var: {runtime_db_uri}")

    if os.getenv('WTF_CSRF_ENABLED') is not None:
        app.config['WTF_CSRF_ENABLED'] = os.getenv('WTF_CSRF_ENABLED').lower() in ('true', '1', 't')
    if os.getenv('TESTING') is not None:
        app.config['TESTING'] = os.getenv('TESTING').lower() in ('true', '1', 't')
    if os.getenv('LOGIN_DISABLED') is not None:
        app.config['LOGIN_DISABLED'] = os.getenv('LOGIN_DISABLED').lower() in ('true', '1', 't')

    logger.info(f"Final SQLALCHEMY_DATABASE_URI: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
    logger.info(f"Final TESTING config: {app.config.get('TESTING')}")

    if not app.config.get('SQLALCHEMY_DATABASE_URI'):
         logger.error("--- DATABASE_URL is NOT SET in config! ---")
         raise RuntimeError("'SQLALCHEMY_DATABASE_URI' must be set via config object or environment variable.")

    # --- Initialize Extensions with the app ---
    logger.info("--- Initializing extensions with app ---")
    try:
        db.init_app(app)
        logger.info("db initialized.")
        migrate.init_app(app, db)
        logger.info("migrate initialized.")
        login_manager.init_app(app)
        logger.info("login_manager initialized.")
        csrf.init_app(app)
        logger.info("csrf initialized.")
    except Exception as e:
        logger.error(f"--- ERROR initializing extensions: {e} ---", exc_info=True)
        raise

    # Configure Flask-Login settings
    login_manager.login_view = 'main_bp.login'
    login_manager.login_message_category = 'info'
    logger.info("--- Flask-Login configured ---")

    # --- Register Blueprints ---
    logger.info("--- Registering blueprints ---")
    try:
        from routes import main_bp
        app.register_blueprint(main_bp)
        logger.info("Successfully registered blueprint 'main_bp' from routes.py")
    except ImportError as e:
        logger.error(f"Could not import 'main_bp' from routes.py: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"An unexpected error occurred during blueprint registration: {e}", exc_info=True)

    # --- Flask-Login User Loader ---
    @login_manager.user_loader
    def load_user(user_id):
        logger.debug(f"Loading user {user_id}")
        return User.query.get(int(user_id))

    logger.info(f"--- EXITING create_app(), returning app: {app.name} ---")
    return app

# --- Helper Functions ---

def get_salary_histogram(country_code, location, job_title):
    """ Fetches salary histogram data from Adzuna. """
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY: return None
    histogram_url = f"{ADZUNA_API_BASE_URL}/{country_code.lower()}/histogram"
    params = {
        'app_id': ADZUNA_APP_ID, 'app_key': ADZUNA_APP_KEY,
        'location0': location, 'what': job_title,
        'content-type': 'application/json'
    }
    logger.info(f"Fetching salary histogram for: {params}")
    try:
        response = requests.get(histogram_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if 'histogram' in data and data['histogram']:
            logger.info("Successfully fetched salary histogram.")
            total_salary = 0; total_count = 0
            for salary_point, count in data['histogram'].items():
                try: total_salary += float(salary_point) * count; total_count += count
                except ValueError: continue
            average_salary = round(total_salary / total_count) if total_count > 0 else None
            return {"histogram": data['histogram'], "average": average_salary}
        else:
            logger.info("No salary histogram data found."); return None
    except requests.exceptions.Timeout: logger.error("Adzuna histogram request timed out."); return None
    except requests.exceptions.HTTPError as e: logger.error(f"Adzuna histogram HTTP Error: {e.response.status_code}. Response: {e.response.text}"); return None
    except requests.exceptions.RequestException as e: logger.error(f"Adzuna histogram connection error: {e}"); return None
    except Exception as e: logger.error(f"Unexpected error fetching salary histogram: {e}"); return None


def get_ai_summary(query_details, total_jobs, job_listings_sample, salary_data):
    """ Calls Azure AI model for an enhanced recruiter-focused summary. """
    if not AZURE_AI_ENDPOINT or not AZURE_AI_KEY:
        logger.warning("Azure AI credentials not configured. Skipping AI summary.")
        return None

    sample_titles = [job['title'] for job in job_listings_sample[:7]]
    sample_descriptions_list = [ job['description'] for job in job_listings_sample[:5] if isinstance(job.get('description'), str) ]
    combined_descriptions = "\n---\n".join(sample_descriptions_list)
    max_desc_length = 1500
    if len(combined_descriptions) > max_desc_length:
        combined_descriptions = combined_descriptions[:max_desc_length] + "..." # Use string ellipsis

    salary_info = "Not available"
    if salary_data and salary_data.get('average'): salary_info = f"approximately {salary_data['average']:,} (currency based on country)"
    elif salary_data and salary_data.get('histogram'): salary_info = "Distribution data available, but average could not be calculated."

    system_message = (
        "You are an AI assistant providing recruitment market analysis for a recruiter. "
        "Focus *only* on the provided data. Use Markdown for formatting (like **bold** and bullet points)."
        "Be concise and direct."
    )
    user_prompt = (
        f"Analyze the job market for a recruiter hiring for '{query_details['what']}' in '{query_details['where']}, {query_details['country'].upper()}'.\n\n"
        f"**Provided Market Data:**\n"
        f"- Total Job Listings Found: {total_jobs}\n"
        f"- Estimated Average Salary: {salary_info}\n"
        f"- Sample Job Titles: {', '.join(sample_titles) if sample_titles else 'N/A'}\n"
        f"- Sample Job Description Excerpts:\n{combined_descriptions if combined_descriptions else 'N/A'}\n\n"
        f"**Recruiter Analysis (Based *strictly* on the text provided above):**\n"
        f"1.  **Market Activity:** Briefly assess the market activity (e.g., high/medium/low volume) based on the total job listings found.\n"
        f"2.  **Specific Skills/Technologies/Tools Mentioned:** List *only* the specific technical skills, programming languages, software tools, frameworks, methodologies (e.g., Agile, Scrum), or required qualifications (e.g., degree names, certifications) that are *explicitly written* in the 'Sample Job Description Excerpts' or 'Sample Job Titles' above. Do *not* infer skills, generalize (e.g., don't say 'cloud skills' if only 'AWS' is mentioned), or list skills not present in the provided text. Present as a bulleted list.\n"
        f"3.  **Sourcing Considerations:** Based *only* on the total job listings number, briefly comment on whether proactive candidate sourcing might be necessary in addition to relying on applications.\n\n"
        f"**Important:** Stick *only* to information directly present in the 'Provided Market Data' section. Do not add outside knowledge or assumptions."
    )

    payload = {
        "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": user_prompt}],
        "max_tokens": 350,
        "temperature": 0.3
    }
    headers = { 'Content-Type': 'application/json', 'api-key': AZURE_AI_KEY }

    # --- ADDED LOGGING ---
    logger.info(f"Attempting to call Azure AI Endpoint: {AZURE_AI_ENDPOINT}")
    try:
        # Log the payload before sending (use json.dumps for pretty printing)
        logger.debug(f"Azure AI Request Payload:\n{json.dumps(payload, indent=2)}")

        response = requests.post(AZURE_AI_ENDPOINT, headers=headers, json=payload, timeout=30)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        response_data = response.json()

        if 'choices' in response_data and len(response_data['choices']) > 0:
            message = response_data['choices'][0].get('message')
            if message and 'content' in message:
                logger.info("Successfully received AI summary.")
                return message['content'].strip()
            else:
                logger.warning(f"Azure AI response 'choices' structure unexpected: {message}")
                return None
        else:
            logger.warning(f"Azure AI response did not contain 'choices'. Response: {response_data}")
            return None
    except requests.exceptions.Timeout:
        logger.error("Azure AI request timed out.")
        return None
    except requests.exceptions.HTTPError as e:
        # --- ADDED LOGGING ---
        # Log the status code and the response text/body for 4xx/5xx errors
        logger.error(f"Azure AI HTTP Error: {e.response.status_code}. Response Body: {e.response.text}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Azure AI connection error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error calling Azure AI endpoint: {e}", exc_info=True) # Log full traceback
        return None


def extract_adzuna_job_id(url):
    """Extracts the Adzuna job ID from the redirect URL."""
    if not url: return None
    try:
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.strip('/').split('/')
        if path_parts:
            potential_id = path_parts[-1]
            if potential_id.isalnum() and len(potential_id) > 5: return potential_id
        query_params = parse_qs(parsed_url.query)
        if 'aid' in query_params: return query_params['aid'][0]
        if 'jobId' in query_params: return query_params['jobId'][0]
        if 'id' in query_params: return query_params['id'][0]
        logger.warning(f"Could not extract Adzuna job ID from URL path or common query params: {url}"); return None
    except Exception as e: logger.error(f"Error parsing Adzuna URL {url}: {e}"); return None


# --- Main Data Fetching Logic ---
def fetch_market_insights(what, where, country, generate_summary=True): # Added generate_summary flag
    """
    Fetches job listings, salary data, and optionally AI summary.
    Returns an 'insights_data' dictionary or None if a critical error occurs.
    """
    logger.info(f"Fetching insights for: what='{what}', where='{where}', country='{country}', generate_summary={generate_summary}")
    if not all([what, where, country]):
        flash("Missing search criteria.", "error")
        return None

    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        flash("Adzuna API credentials not configured.", "error")
        return None

    # Initialize data containers
    insights_data = None
    adzuna_data = None
    job_listings = []
    total_jobs = 0
    salary_data = None
    ai_summary_html = None # Default to None

    query_details = {'what': what, 'where': where, 'country': country}

    # --- 1. Call Adzuna Search API ---
    api_url = f"{ADZUNA_API_BASE_URL}/{country.lower()}/search/1"
    params = { 'app_id': ADZUNA_APP_ID, 'app_key': ADZUNA_APP_KEY, 'what': what, 'where': where, 'results_per_page': RESULTS_PER_PAGE, 'content-type': 'application/json' }
    try:
        logger.info(f"Fetching Adzuna data for: {params}")
        response = requests.get(api_url, params=params, timeout=20)
        response.raise_for_status()
        adzuna_data = response.json()
        logger.info("Successfully fetched data from Adzuna.")

        total_jobs = adzuna_data.get('count', 0)
        results = adzuna_data.get('results', [])
        for job in results:
            adzuna_url = job.get('redirect_url')
            adzuna_job_id = extract_adzuna_job_id(adzuna_url)
            if adzuna_job_id: job_listings.append({ "adzuna_job_id": adzuna_job_id, "title": job.get('title'), "company": job.get('company', {}).get('display_name', 'N/A'), "location": job.get('location', {}).get('display_name', 'N/A'), "description": job.get('description', 'No description available.'), "url": adzuna_url, "created": job.get('created') })
            else: logger.warning(f"Skipping job due to missing Adzuna ID: {job.get('title')}")

    except requests.exceptions.Timeout: flash("Adzuna search request timed out. Please try again.", "error"); return None
    except requests.exceptions.HTTPError as e: flash(f"Adzuna API Error ({e.response.status_code}). Please check search terms or try again later.", "error"); return None
    except requests.exceptions.RequestException as e: flash("Could not connect to Adzuna. Please check your connection or try again later.", "error"); return None
    except Exception as e: logger.error(f"Unexpected error during Adzuna search: {e}"); flash("An internal server error occurred while fetching job listings.", "error"); return None

    # --- 2. Call Adzuna Histogram (Salary) ---
    salary_data = get_salary_histogram(country, where, what)

    # --- 3. Call Azure AI Summary (Conditional) ---
    if generate_summary: # Only call if the flag is True
        logger.info("Generate summary flag is true, calling get_ai_summary.")
        ai_summary_raw = get_ai_summary(query_details, total_jobs, job_listings[:10], salary_data)
        if ai_summary_raw:
            html_summary = markdown.markdown(ai_summary_raw, extensions=['fenced_code', 'tables'])
            ai_summary_html = Markup(html_summary)
        else:
            logger.warning("AI summary generation was requested but failed or returned no content.")
            # Optionally flash a message here if desired
            # flash("Could not generate AI summary.", "warning")
    else:
        logger.info("Generate summary flag is false, skipping AI summary call.")


    # --- 4. Assemble final insights ---
    insights_data = {
        "query": query_details,
        "total_matching_jobs": total_jobs,
        "job_listings": job_listings,
        "salary_data": salary_data,
        "ai_summary_html": ai_summary_html # Will be None if generate_summary was False or AI failed
    }
    return insights_data


# --- Run development server (if script is executed directly) ---
if __name__ == '__main__':
    dev_app = create_app()
    dev_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)),
            debug=os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 't'))

