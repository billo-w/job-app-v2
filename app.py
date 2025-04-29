import os
import requests
from flask import (Flask, request, jsonify, render_template, flash, redirect,
                   url_for, session) # Added jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import (LoginManager, UserMixin, login_user, logout_user,
                         login_required, current_user)
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect, generate_csrf # Import CSRFProtect and generate_csrf
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
app.config['SQLALCHEMY_ECHO'] = False # Set to True for debugging SQL queries
# Optional: Configure WTF_CSRF_ENABLED (default is True)
# app.config['WTF_CSRF_ENABLED'] = True

# --- Extensions Initialization ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
csrf = CSRFProtect(app) # Initialize CSRF protection
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# --- Adzuna & AI Configuration ---
ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID')
ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY')
ADZUNA_API_BASE_URL = 'https://api.adzuna.com/v1/api/jobs'
RESULTS_PER_PAGE = 20
AZURE_AI_ENDPOINT = os.getenv('AZURE_AI_ENDPOINT')
AZURE_AI_KEY = os.getenv('AZURE_AI_KEY')

# --- Database Models ---
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

# --- Forms (using Flask-WTF) ---
# Note: CSRF protection is handled globally by Flask-WTF/CSRFProtect
# but forms still need the hidden tag rendered in the template.
# For AJAX, we send the token via headers.

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

# --- Helper Functions (Adzuna, AI, Data Fetching) ---
# Keep get_salary_histogram, get_ai_summary, extract_adzuna_job_id,
# and fetch_market_insights functions as they were in the PRG version.
# (Code omitted for brevity, assume they are present and correct)
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
        # Avoid flashing here for AJAX, return None or specific error info
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

    sample_titles = [job['title'] for job in job_listings_sample[:7]] # Limit sample size
    # Ensure description is a string before joining
    sample_descriptions = " ".join([
        job['description'] for job in job_listings_sample[:5]
        if isinstance(job.get('description'), str)
    ])
    max_desc_length = 1000 # Limit description length for prompt
    if len(sample_descriptions) > max_desc_length:
        sample_descriptions = sample_descriptions[:max_desc_length] + "..."

    salary_info = "Not available"
    if salary_data and salary_data.get('average'):
        salary_info = f"approximately {salary_data['average']:,} (currency based on country)"
    elif salary_data and salary_data.get('histogram'):
        salary_info = "Distribution data available, but average could not be calculated."

    system_message = ("You are an AI assistant providing recruitment market analysis. Focus on actionable insights for a recruiter based *only* on the provided data. Use Markdown for formatting (like **bold**).")
    user_prompt = (
        f"Analyze the job market for a recruiter hiring for '{query_details['what']}' in '{query_details['where']}, {query_details['country'].upper()}'.\n\n"
        f"**Market Data:**\n"
        f"- Total Job Listings Found: {total_jobs}\n"
        f"- Estimated Average Salary: {salary_info}\n"
        f"- Sample Job Titles: {', '.join(sample_titles) if sample_titles else 'N/A'}\n"
        f"- Sample Job Description Excerpts: {sample_descriptions if sample_descriptions else 'N/A'}\n\n"
        f"**Recruiter Analysis (Based *only* on above data - use Markdown for emphasis):**\n"
        f"1.  **Market Activity & Competitiveness:** Based on job volume and salary data (if available), how active/competitive does this market seem?\n"
        f"2.  **Key Skills/Keywords:** Based *only* on the sample titles and descriptions, what 2-3 potential key skills or technologies seem commonly required?\n"
        f"3.  **Candidate Pool & Sourcing:** What does the job volume suggest about the likely candidate pool size and the potential need for proactive sourcing vs. relying on applications?\n\n"
        f"Provide a concise, bulleted summary. Do not invent skills or salary details not present in the data."
    )

    payload = {
        "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": user_prompt}],
        "max_tokens": 250, # Adjust as needed
        "temperature": 0.5
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
        # Avoid flashing here for AJAX
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


def fetch_market_insights(what, where, country):
    """
    Fetches job listings, salary data, and AI summary based on search criteria.
    Returns an 'insights_data' dictionary or None if a critical error occurs.
    Handles flashing messages for user feedback during page loads.
    """
    if not all([what, where, country]):
        flash("Missing search criteria.", "error")
        return None

    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        flash("Adzuna API credentials not configured.", "error")
        return None

    insights_data = None
    salary_data = None
    ai_summary_html = None
    query_details = {'what': what, 'where': where, 'country': country}

    # --- Call Adzuna Search API ---
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
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        data = response.json()
        app.logger.info("Successfully fetched data from Adzuna.")

        total_jobs = data.get('count', 0)
        results = data.get('results', [])
        job_listings = []
        for job in results:
            adzuna_url = job.get('redirect_url')
            adzuna_job_id = extract_adzuna_job_id(adzuna_url) # Use helper function
            if adzuna_job_id: # Only include jobs where we could extract an ID
                job_listings.append({
                    "adzuna_job_id": adzuna_job_id, # Add the extracted ID
                    "title": job.get('title'),
                    "company": job.get('company', {}).get('display_name', 'N/A'),
                    "location": job.get('location', {}).get('display_name', 'N/A'),
                    "description": job.get('description', 'No description available.'),
                    "url": adzuna_url,
                    "created": job.get('created')
                })
            else:
                app.logger.warning(f"Skipping job due to missing Adzuna ID: {job.get('title')}")

        # --- Call Adzuna Histogram & Azure AI ---
        # Pass errors from helpers up if needed, or let them return None
        salary_data = get_salary_histogram(country, where, what)
        ai_summary_raw = get_ai_summary(query_details, total_jobs, job_listings[:10], salary_data) # Pass limited sample
        if ai_summary_raw:
            # Convert Markdown summary to HTML
            html_summary = markdown.markdown(ai_summary_raw, extensions=['fenced_code', 'tables'])
            ai_summary_html = Markup(html_summary) # Mark as safe HTML

        # --- Assemble final insights ---
        insights_data = {
            "query": query_details,
            "total_matching_jobs": total_jobs,
            "job_listings": job_listings,
            "salary_data": salary_data,
            "ai_summary_html": ai_summary_html
        }
        return insights_data

    # --- Error Handling for Adzuna Search ---
    except requests.exceptions.Timeout:
        flash("Adzuna search request timed out. Please try again.", "error")
        return None
    except requests.exceptions.HTTPError as e:
        flash(f"Adzuna API Error ({e.response.status_code}). Please check search terms or try again later.", "error")
        return None
    except requests.exceptions.RequestException as e:
        flash("Could not connect to Adzuna. Please check your connection or try again later.", "error")
        return None
    except Exception as e:
        app.logger.error(f"Unexpected error during insight fetching: {e}")
        flash("An internal server error occurred while fetching insights.", "error")
        return None

# --- Routes ---

# Keep home() and get_insights() routes as they were in the PRG version
@app.route('/')
def home():
    """
    Renders the main search page.
    If search parameters are provided via GET, fetches and displays results.
    """
    # Use .get(key, '') to provide default empty string if key is missing
    what = request.args.get('what', '')
    where = request.args.get('where', '')
    country = request.args.get('country', '')
    form_data = {'what': what, 'where': where, 'country': country} # For pre-filling form

    insights_data = None
    saved_job_ids = set()

    # If search parameters are present (and not empty strings), fetch insights
    if what and where and country: # Check if values are truthy
        app.logger.info(f"Home route received search parameters: {form_data}")
        insights_data = fetch_market_insights(what, where, country)
        # insights_data will be None if fetch_market_insights encountered an error and flashed a message

    # Get saved job IDs for the current user regardless of search
    if current_user.is_authenticated:
        saved_job_ids = {job.adzuna_job_id for job in current_user.saved_jobs}

    return render_template('index.html',
                           insights=insights_data,
                           form_data=form_data, # Pass form_data to pre-fill search boxes
                           saved_job_ids=saved_job_ids)


@app.route('/insights', methods=['POST'])
def get_insights():
    """
    Handles the POST from the search form.
    Redirects to the 'home' route with search parameters as GET query args (PRG Pattern).
    """
    what = request.form.get('what')
    where = request.form.get('where')
    country = request.form.get('country')

    if not all([what, where, country]):
        flash("Please fill in all search fields.", "error")
        # Redirect back to the empty home page if validation fails
        return redirect(url_for('home'))

    # Redirect to the home route with parameters in the query string
    return redirect(url_for('home', what=what, where=where, country=country))


# --- Authentication Routes ---
# Keep register(), login(), logout() as they were in the PRG version
# (Code omitted for brevity)
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

# --- Saved Jobs Routes (AJAX Handlers) ---

@app.route('/save_job', methods=['POST'])
@login_required
def save_job():
    """Handles AJAX request to save a job."""
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'Invalid request format.'}), 400

    adzuna_job_id = data.get('adzuna_job_id')
    title = data.get('title')
    company = data.get('company')
    location = data.get('location')
    adzuna_url = data.get('adzuna_url')

    if not all([adzuna_job_id, title, adzuna_url]):
        return jsonify({'status': 'error', 'message': 'Missing job details.'}), 400

    # Check if already saved
    existing_save = SavedJob.query.filter_by(user_id=current_user.id, adzuna_job_id=adzuna_job_id).first()
    if existing_save:
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
        return jsonify({'status': 'success', 'message': 'Job saved!'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error saving job {adzuna_job_id} for user {current_user.id} via AJAX: {e}")
        return jsonify({'status': 'error', 'message': 'Database error saving job.'}), 500


@app.route('/unsave_job', methods=['POST'])
@login_required
def unsave_job():
    """Handles AJAX request to unsave a job."""
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'Invalid request format.'}), 400

    adzuna_job_id = data.get('adzuna_job_id')
    if not adzuna_job_id:
        return jsonify({'status': 'error', 'message': 'Missing job ID.'}), 400

    job_to_unsave = SavedJob.query.filter_by(user_id=current_user.id, adzuna_job_id=adzuna_job_id).first()
    if job_to_unsave:
        db.session.delete(job_to_unsave)
        try:
            db.session.commit()
            app.logger.info(f"User {current_user.id} unsaved job {adzuna_job_id} via AJAX")
            return jsonify({'status': 'success', 'message': 'Job removed.'})
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error unsaving job {adzuna_job_id} for user {current_user.id} via AJAX: {e}")
            return jsonify({'status': 'error', 'message': 'Database error unsaving job.'}), 500
    else:
        # Job might have already been unsaved or never existed for user
        app.logger.warning(f"Attempt to unsave non-existent/already unsaved job {adzuna_job_id} for user {current_user.id}")
        return jsonify({'status': 'error', 'message': 'Job not found in saved list.'}), 404 # 404 Not Found


# --- Saved Jobs Page Route (Remains standard Flask route) ---
@app.route('/saved_jobs')
@login_required
def saved_jobs_list():
    """Displays the list of jobs saved by the current user."""
    jobs = SavedJob.query.filter_by(user_id=current_user.id).order_by(SavedJob.id.desc()).all()
    # Note: Unsaving from this page still uses standard form submission
    # unless you add AJAX handling to saved_jobs.html as well.
    return render_template('saved_jobs.html', title='Saved Jobs', jobs=jobs)


# --- Main execution ---
if __name__ == '__main__':
    # Use Gunicorn or another WSGI server in production instead of app.run()
    # Debug should be False in production
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=False) # Set debug=True for development if needed

