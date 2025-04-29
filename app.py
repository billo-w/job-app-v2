import os
import requests
import time # Import time for token expiry
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
logging.basicConfig(level=logging.INFO)
load_dotenv()

# Initialize Flask App
app = Flask(__name__, template_folder='templates')

# --- Configuration ---
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'a_very_secret_dev_key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = False

# --- Extensions Initialization ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
csrf = CSRFProtect(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# --- API Configuration ---
ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID')
ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY')
ADZUNA_API_BASE_URL = 'https://api.adzuna.com/v1/api/jobs'
RESULTS_PER_PAGE = 20
AZURE_AI_ENDPOINT = os.getenv('AZURE_AI_ENDPOINT')
AZURE_AI_KEY = os.getenv('AZURE_AI_KEY')
# Lightcast Config
LIGHTCAST_CLIENT_ID = os.getenv('LIGHTCAST_CLIENT_ID')
LIGHTCAST_CLIENT_SECRET = os.getenv('LIGHTCAST_CLIENT_SECRET')
LIGHTCAST_AUTH_URL = 'https://auth.emsicloud.com/connect/token'
LIGHTCAST_API_BASE_URL = 'https://emsiservices.com' # Base URL for titles API

# --- Simple In-Memory Cache for Lightcast Token ---
lightcast_token_cache = {
    "access_token": None,
    "expires_at": 0
}

# --- Database Models ---
# (User and SavedJob models remain the same - omitted for brevity)
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


# --- Flask-Login User Loader ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Forms ---
# (RegistrationForm and LoginForm remain the same - omitted for brevity)
class RegistrationForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password', message='Passwords must match.')])
    submit = SubmitField('Register')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('That email is already taken. Please choose a different one or login.')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')

# --- Helper Functions ---

# --- Lightcast Helper Functions ---
def get_lightcast_token():
    """Gets a valid Lightcast access token, using cache or fetching a new one."""
    global lightcast_token_cache
    current_time = time.time()

    # Check cache validity (with a small buffer)
    if lightcast_token_cache["access_token"] and lightcast_token_cache["expires_at"] > current_time + 60:
        app.logger.info("Using cached Lightcast token.")
        return lightcast_token_cache["access_token"]

    # Fetch new token if cache is invalid or missing
    if not LIGHTCAST_CLIENT_ID or not LIGHTCAST_CLIENT_SECRET:
        app.logger.error("Lightcast Client ID or Secret not configured.")
        return None

    payload = {
        'client_id': LIGHTCAST_CLIENT_ID,
        'client_secret': LIGHTCAST_CLIENT_SECRET,
        'grant_type': 'client_credentials',
        'scope': 'emsi_open' # Scope for Titles API (check Lightcast docs if different)
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    app.logger.info("Requesting new Lightcast access token.")

    try:
        response = requests.post(LIGHTCAST_AUTH_URL, data=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        access_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600) # Default to 1 hour if not provided

        if not access_token:
            app.logger.error("Failed to get access_token from Lightcast response.")
            return None

        # Update cache
        lightcast_token_cache["access_token"] = access_token
        lightcast_token_cache["expires_at"] = current_time + expires_in
        app.logger.info("Successfully obtained and cached new Lightcast token.")
        return access_token

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error requesting Lightcast token: {e}")
        return None
    except Exception as e:
         app.logger.error(f"Unexpected error getting Lightcast token: {e}")
         return None


def get_lightcast_skills(job_title):
    """Fetches common skills for a job title using Lightcast Titles API."""
    if not job_title:
        return None

    access_token = get_lightcast_token()
    if not access_token:
        app.logger.error("Cannot fetch Lightcast skills without access token.")
        # Avoid flashing here, let fetch_market_insights handle overall errors
        return None

    headers = {'Authorization': f'Bearer {access_token}'}

    # 1. Normalize the job title to get Lightcast Title ID
    normalize_url = f"{LIGHTCAST_API_BASE_URL}/titles/normalize"
    normalize_params = {'q': job_title, 'limit': 1} # Limit to best match
    normalized_title_id = None

    app.logger.info(f"Normalizing job title '{job_title}' with Lightcast.")
    try:
        response = requests.get(normalize_url, headers=headers, params=normalize_params, timeout=10)
        response.raise_for_status()
        normalize_data = response.json()

        if normalize_data and 'data' in normalize_data and normalize_data['data']:
            normalized_title_id = normalize_data['data'][0].get('id')
            app.logger.info(f"Normalized '{job_title}' to Lightcast ID: {normalized_title_id}")
        else:
            app.logger.warning(f"Could not normalize job title '{job_title}' via Lightcast.")
            return None # Cannot proceed without ID

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error normalizing Lightcast title: {e}")
        return None
    except Exception as e:
         app.logger.error(f"Unexpected error during Lightcast title normalization: {e}")
         return None

    # 2. Fetch Title details (including skills) using the ID
    if not normalized_title_id:
        return None

    details_url = f"{LIGHTCAST_API_BASE_URL}/titles/{normalized_title_id}"
    # Include 'fields=mapping' to ensure skills are returned
    details_params = {'fields': 'mapping'}

    app.logger.info(f"Fetching skills for Lightcast ID: {normalized_title_id}")
    try:
        response = requests.get(details_url, headers=headers, params=details_params, timeout=10)
        response.raise_for_status()
        details_data = response.json()

        if details_data and 'data' in details_data and 'mapping' in details_data['data'] and 'skills' in details_data['data']['mapping']:
            skills_list = [skill.get('name') for skill in details_data['data']['mapping']['skills'] if skill.get('name')]
            app.logger.info(f"Found {len(skills_list)} skills for '{job_title}' (ID: {normalized_title_id})")
            return skills_list[:15] # Return top 15 skills for brevity
        else:
            app.logger.warning(f"No skills found in Lightcast mapping for ID: {normalized_title_id}")
            return None

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error fetching Lightcast title details/skills: {e}")
        return None
    except Exception as e:
         app.logger.error(f"Unexpected error fetching Lightcast skills: {e}")
         return None

# --- Other Helper Functions (Adzuna, AI, etc.) ---
# (get_salary_histogram, get_ai_summary, extract_adzuna_job_id remain the same - omitted for brevity)
def get_salary_histogram(country_code, location, job_title):
    """ Fetches salary histogram data from Adzuna. """
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY: return None
    histogram_url = f"{ADZUNA_API_BASE_URL}/{country_code.lower()}/histogram"
    params = {
        'app_id': ADZUNA_APP_ID, 'app_key': ADZUNA_APP_KEY,
        'location0': location, 'what': job_title,
        'content-type': 'application/json'
    }
    app.logger.info(f"Fetching salary histogram for: {params}")
    try:
        response = requests.get(histogram_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if 'histogram' in data and data['histogram']:
            app.logger.info("Successfully fetched salary histogram.")
            total_salary = 0
            total_count = 0
            for salary_point, count in data['histogram'].items():
                try:
                    total_salary += float(salary_point) * count
                    total_count += count
                except ValueError:
                    continue # Skip non-numeric salary points if any
            average_salary = round(total_salary / total_count) if total_count > 0 else None
            return {"histogram": data['histogram'], "average": average_salary}
        else:
            app.logger.info("No salary histogram data found.")
            return None
    except requests.exceptions.Timeout:
        app.logger.error("Adzuna histogram request timed out.")
        return None
    except requests.exceptions.HTTPError as e:
        app.logger.error(f"Adzuna histogram HTTP Error: {e.response.status_code}.")
        return None
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Adzuna histogram connection error: {e}")
        return None
    except Exception as e:
        app.logger.error(f"Unexpected error fetching salary histogram: {e}")
        return None


def get_ai_summary(query_details, total_jobs, job_listings_sample, salary_data):
    """ Calls Azure AI model for an enhanced recruiter-focused summary. """
    if not AZURE_AI_ENDPOINT or not AZURE_AI_KEY:
        app.logger.warning("Azure AI credentials not configured. Skipping AI summary.")
        return None

    sample_titles = [job['title'] for job in job_listings_sample[:7]]
    sample_descriptions = " ".join([
        job['description'] for job in job_listings_sample[:5]
        if isinstance(job.get('description'), str)
    ])
    max_desc_length = 1000
    if len(sample_descriptions) > max_desc_length:
        sample_descriptions = sample_descriptions[:max_desc_length] + "..."

    salary_info = "Not available"
    if salary_data and salary_data.get('average'):
        salary_info = f"approximately {salary_data['average']:,} (currency based on country)"
    elif salary_data and salary_data.get('histogram'):
        salary_info = "Distribution data available, but average could not be calculated."

    system_message = ("You are an AI assistant providing recruitment market analysis. Focus on actionable insights for a recruiter based *only* on the provided data. Use Markdown for formatting (like **bold**).")
    # --- MODIFIED PROMPT ---
    user_prompt = (
        f"Analyze the job market for a recruiter hiring for '{query_details['what']}' in '{query_details['where']}, {query_details['country'].upper()}'.\n\n"
        f"**Market Data:**\n"
        f"- Total Job Listings Found: {total_jobs}\n"
        f"- Estimated Average Salary: {salary_info}\n"
        f"- Sample Job Titles: {', '.join(sample_titles) if sample_titles else 'N/A'}\n"
        f"- Sample Job Description Excerpts: {sample_descriptions if sample_descriptions else 'N/A'}\n\n"
        f"**Recruiter Analysis (Based *only* on above data - use Markdown for emphasis):**\n"
        f"1.  **Market Activity & Competitiveness:** Based on job volume and salary data (if available), how active/competitive does this market seem?\n"
        f"2.  **Specific Skills/Keywords Mentioned:** List the specific skills, technologies, tools, or qualifications explicitly mentioned in the sample job titles and descriptions provided above. Do not generalize or infer skills not present in the text.\n" # Changed instruction here
        f"3.  **Candidate Pool & Sourcing:** What does the job volume suggest about the likely candidate pool size and the potential need for proactive sourcing vs. relying on applications?\n\n"
        f"Provide a concise, bulleted summary. Do not invent skills or salary details not present in the data."
    )
    # --- END MODIFIED PROMPT ---

    payload = {
        "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": user_prompt}],
        "max_tokens": 300, # Slightly increased tokens in case skill list is longer
        "temperature": 0.4 # Slightly lower temperature to encourage factual listing
    }
    headers = {
        'Content-Type': 'application/json',
        'api-key': AZURE_AI_KEY
    }
    app.logger.info(f"Sending enhanced recruiter request to Azure AI Endpoint: {AZURE_AI_ENDPOINT}")
    try:
        response = requests.post(AZURE_AI_ENDPOINT, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        response_data = response.json()
        if 'choices' in response_data and len(response_data['choices']) > 0:
            message = response_data['choices'][0].get('message')
            if message and 'content' in message:
                app.logger.info("Successfully received AI summary.")
                return message['content'].strip()
            else:
                app.logger.warning(f"Azure AI response 'choices' structure unexpected: {message}")
                return None
        else:
            app.logger.warning(f"Azure AI response did not contain 'choices'. Response: {response_data}")
            return None
    except requests.exceptions.Timeout:
        app.logger.error("Azure AI request timed out.")
        return None
    except requests.exceptions.HTTPError as e:
        app.logger.error(f"Azure AI HTTP Error: {e.response.status_code}.")
        return None
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Azure AI connection error: {e}")
        return None
    except Exception as e:
        app.logger.error(f"Unexpected error calling Azure AI endpoint: {e}")
        return None


def extract_adzuna_job_id(url):
    """Extracts the Adzuna job ID from the redirect URL."""
    if not url:
        return None
    try:
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.strip('/').split('/')
        if path_parts:
            potential_id = path_parts[-1]
            if potential_id.isalnum() and len(potential_id) > 5:
                 return potential_id
        query_params = parse_qs(parsed_url.query)
        if 'aid' in query_params: return query_params['aid'][0]
        if 'jobId' in query_params: return query_params['jobId'][0]
        if 'id' in query_params: return query_params['id'][0]
        app.logger.warning(f"Could not extract Adzuna job ID from URL path or common query params: {url}")
        return None
    except Exception as e:
        app.logger.error(f"Error parsing Adzuna URL {url}: {e}")
        return None


# --- Main Data Fetching Logic ---
def fetch_market_insights(what, where, country):
    """
    Fetches job listings, salary data, AI summary, and Lightcast skills.
    Returns an 'insights_data' dictionary or None if a critical error occurs.
    """
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
    ai_summary_html = None
    common_skills = None # Initialize common_skills

    query_details = {'what': what, 'where': where, 'country': country}

    # --- 1. Call Adzuna Search API ---
    api_url = f"{ADZUNA_API_BASE_URL}/{country.lower()}/search/1"
    params = {
        'app_id': ADZUNA_APP_ID, 'app_key': ADZUNA_APP_KEY,
        'what': what, 'where': where,
        'results_per_page': RESULTS_PER_PAGE,
        'content-type': 'application/json'
    }
    try:
        app.logger.info(f"Fetching Adzuna data for: {params}")
        response = requests.get(api_url, params=params, timeout=20)
        response.raise_for_status()
        adzuna_data = response.json()
        app.logger.info("Successfully fetched data from Adzuna.")

        total_jobs = adzuna_data.get('count', 0)
        results = adzuna_data.get('results', [])
        for job in results:
            adzuna_url = job.get('redirect_url')
            adzuna_job_id = extract_adzuna_job_id(adzuna_url)
            if adzuna_job_id:
                job_listings.append({
                    "adzuna_job_id": adzuna_job_id,
                    "title": job.get('title'),
                    "company": job.get('company', {}).get('display_name', 'N/A'),
                    "location": job.get('location', {}).get('display_name', 'N/A'),
                    "description": job.get('description', 'No description available.'),
                    "url": adzuna_url,
                    "created": job.get('created')
                })
            else:
                app.logger.warning(f"Skipping job due to missing Adzuna ID: {job.get('title')}")

    except requests.exceptions.Timeout:
        flash("Adzuna search request timed out. Please try again.", "error")
        return None # Critical error, stop processing
    except requests.exceptions.HTTPError as e:
        flash(f"Adzuna API Error ({e.response.status_code}). Please check search terms or try again later.", "error")
        return None # Critical error
    except requests.exceptions.RequestException as e:
        flash("Could not connect to Adzuna. Please check your connection or try again later.", "error")
        return None # Critical error
    except Exception as e:
        app.logger.error(f"Unexpected error during Adzuna search: {e}")
        flash("An internal server error occurred while fetching job listings.", "error")
        return None # Critical error

    # --- 2. Call Adzuna Histogram (Salary) ---
    salary_data = get_salary_histogram(country, where, what)
    # Continue even if salary data fails

    # --- 3. Call Lightcast Skills API ---
    common_skills = get_lightcast_skills(what) # Use the 'what' field
    if common_skills is None:
        app.logger.warning(f"Could not retrieve common skills for '{what}' from Lightcast.")
        # Optionally flash a message, but continue processing
        # flash("Could not retrieve common skills data.", "info")
    # Continue even if skills data fails

    # --- 4. Call Azure AI Summary ---
    ai_summary_raw = get_ai_summary(query_details, total_jobs, job_listings[:10], salary_data)
    if ai_summary_raw:
        html_summary = markdown.markdown(ai_summary_raw, extensions=['fenced_code', 'tables'])
        ai_summary_html = Markup(html_summary)
    # Continue even if AI summary fails

    # --- 5. Assemble final insights ---
    insights_data = {
        "query": query_details,
        "total_matching_jobs": total_jobs,
        "job_listings": job_listings,
        "salary_data": salary_data,
        "ai_summary_html": ai_summary_html,
        "common_skills": common_skills # Add the fetched skills
    }
    return insights_data


# --- Routes ---

@app.route('/')
def home():
    """ Renders the main search page or results based on GET parameters. """
    what = request.args.get('what', '')
    where = request.args.get('where', '')
    country = request.args.get('country', '')
    form_data = {'what': what, 'where': where, 'country': country}

    insights_data = None
    saved_job_ids = set()

    if what and where and country:
        app.logger.info(f"Home route received search parameters: {form_data}")
        insights_data = fetch_market_insights(what, where, country)

    if current_user.is_authenticated:
        saved_job_ids = {job.adzuna_job_id for job in current_user.saved_jobs}

    return render_template('index.html',
                           insights=insights_data,
                           form_data=form_data,
                           saved_job_ids=saved_job_ids)


@app.route('/insights', methods=['POST'])
def get_insights():
    """ Handles the POST from the search form (PRG Pattern). """
    what = request.form.get('what')
    where = request.form.get('where')
    country = request.form.get('country')

    if not all([what, where, country]):
        flash("Please fill in all search fields.", "error")
        return redirect(url_for('home'))

    return redirect(url_for('home', what=what, where=where, country=country))


# --- Authentication Routes ---
# (register, login, logout remain the same - omitted for brevity)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home')) # Redirect if already logged in
    form = RegistrationForm()
    if form.validate_on_submit():
        # Create new user
        user = User(email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        try:
            db.session.commit()
            flash('Congratulations, you are now a registered user! Please login.', 'success')
            app.logger.info(f"New user registered: {form.email.data}")
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error registering user {form.email.data}: {e}")
            flash('An error occurred during registration. Please try again.', 'error')
    return render_template('register.html', title='Register', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home')) # Redirect if already logged in
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid email or password.', 'error')
            # No redirect here, just re-render the login form with the error
        else:
            # Log the user in
            login_user(user, remember=form.remember.data) # Use remember value from form
            flash(f'Welcome back, {user.email}!', 'success')
            app.logger.info(f"User logged in: {user.email}")
            # Redirect to the page the user was trying to access, or home
            next_page = request.args.get('next')
            # Basic security check for next_page to prevent open redirect
            if next_page and urlparse(next_page).netloc == '':
                 app.logger.info(f"Redirecting logged in user to: {next_page}")
                 return redirect(next_page)
            else:
                 app.logger.info("Redirecting logged in user to home.")
                 return redirect(url_for('home'))
    # Render login page on GET or if form validation fails
    return render_template('login.html', title='Login', form=form)


@app.route('/logout')
@login_required # Ensure user is logged in to logout
def logout():
    app.logger.info(f"User logged out: {current_user.email}")
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

# --- Saved Jobs Routes (AJAX Handlers + Form Handler) ---
# (save_job and unsave_job remain the same - omitted for brevity)
@app.route('/save_job', methods=['POST'])
@login_required
def save_job():
    """Handles AJAX request to save a job."""
    # Check if the request is JSON (from index page AJAX)
    if request.is_json:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'Invalid JSON request.'}), 400
        adzuna_job_id = data.get('adzuna_job_id')
        title = data.get('title')
        company = data.get('company')
        location = data.get('location')
        adzuna_url = data.get('adzuna_url')
        is_ajax = True
    else:
        # Fallback or handle potential non-AJAX POST if needed
        # For now, assume save only happens via AJAX from index
        app.logger.warning("Received non-JSON POST request to /save_job")
        return jsonify({'status': 'error', 'message': 'Unsupported request format.'}), 415


    if not all([adzuna_job_id, title, adzuna_url]):
         # Return JSON error for AJAX
        return jsonify({'status': 'error', 'message': 'Missing job details.'}), 400

    # Check if already saved
    existing_save = SavedJob.query.filter_by(user_id=current_user.id, adzuna_job_id=adzuna_job_id).first()
    if existing_save:
        # Return JSON error for AJAX
        return jsonify({'status': 'error', 'message': 'Job already saved.'}), 409 # 409 Conflict

    # Create and save the job
    saved_job = SavedJob(
        adzuna_job_id=adzuna_job_id, title=title, company=company,
        location=location, adzuna_url=adzuna_url, user_id=current_user.id
    )
    db.session.add(saved_job)
    try:
        db.session.commit()
        app.logger.info(f"User {current_user.id} saved job {adzuna_job_id} via AJAX")
         # Return JSON success for AJAX
        return jsonify({'status': 'success', 'message': 'Job saved!'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error saving job {adzuna_job_id} for user {current_user.id} via AJAX: {e}")
        # Return JSON error for AJAX
        return jsonify({'status': 'error', 'message': 'Database error saving job.'}), 500


@app.route('/unsave_job', methods=['POST'])
@login_required
def unsave_job():
    """
    Handles both AJAX (JSON) requests from index page
    and standard form POST requests from saved_jobs page.
    """
    is_ajax = False
    adzuna_job_id = None

    # Check content type to determine request source
    if request.is_json:
        is_ajax = True
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'Invalid JSON request.'}), 400
        adzuna_job_id = data.get('adzuna_job_id')
        app.logger.info(f"Received AJAX unsave request for job ID: {adzuna_job_id}")

    elif request.form:
        # Handle standard form submission from saved_jobs.html
        adzuna_job_id = request.form.get('adzuna_job_id')
        app.logger.info(f"Received Form unsave request for job ID: {adzuna_job_id}")
        # CSRF token is validated automatically by Flask-CSRFProtect for form posts

    else:
        # Neither JSON nor Form data found
        app.logger.error("Unsave request received without valid JSON or Form data.")
        # Return appropriate error based on expected content type or a generic one
        return "Unsupported Media Type", 415

    # --- Common Logic ---
    if not adzuna_job_id:
        message = 'Missing job ID.'
        if is_ajax:
            return jsonify({'status': 'error', 'message': message}), 400
        else:
            flash(message, 'error')
            return redirect(url_for('saved_jobs_list')) # Redirect back for form

    job_to_unsave = SavedJob.query.filter_by(user_id=current_user.id, adzuna_job_id=adzuna_job_id).first()

    if job_to_unsave:
        db.session.delete(job_to_unsave)
        try:
            db.session.commit()
            message = 'Job removed from saved list.'
            app.logger.info(f"User {current_user.id} unsaved job {adzuna_job_id}")
            if is_ajax:
                return jsonify({'status': 'success', 'message': message})
            else:
                flash(message, 'success')
                return redirect(url_for('saved_jobs_list')) # Redirect back for form
        except Exception as e:
            db.session.rollback()
            message = 'Database error unsaving job.'
            app.logger.error(f"Error unsaving job {adzuna_job_id} for user {current_user.id}: {e}")
            if is_ajax:
                return jsonify({'status': 'error', 'message': message}), 500
            else:
                flash(message, 'error')
                return redirect(url_for('saved_jobs_list')) # Redirect back for form
    else:
        # Job not found
        message = 'Job not found in your saved list.'
        app.logger.warning(f"Attempt to unsave non-existent/already unsaved job {adzuna_job_id} for user {current_user.id}")
        if is_ajax:
            return jsonify({'status': 'error', 'message': message}), 404 # 404 Not Found
        else:
            flash(message, 'warning')
            return redirect(url_for('saved_jobs_list')) # Redirect back for form


# --- Saved Jobs Page Route ---
@app.route('/saved_jobs')
@login_required
def saved_jobs_list():
    """Displays the list of jobs saved by the current user."""
    jobs = SavedJob.query.filter_by(user_id=current_user.id).order_by(SavedJob.id.desc()).all()
    return render_template('saved_jobs.html', title='Saved Jobs', jobs=jobs)


# --- Main execution ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=False)

