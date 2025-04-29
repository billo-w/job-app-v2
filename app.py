import os
import requests
from flask import (Flask, request, jsonify, render_template, flash, redirect,
                   url_for, session) # Added redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import (LoginManager, UserMixin, login_user, logout_user,
                       login_required, current_user) # Added Flask-Login imports
from flask_wtf import FlaskForm # Added Flask-WTF
from wtforms import StringField, PasswordField, SubmitField # Added Form fields
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError # Added validators
from werkzeug.security import generate_password_hash, check_password_hash # For passwords
from dotenv import load_dotenv
import logging
import markdown
from markupsafe import Markup
from urllib.parse import urlparse, parse_qs # To extract Adzuna job key

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO)
load_dotenv()

# Initialize Flask App
app = Flask(__name__, template_folder='templates')

# --- Configuration ---
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'a_very_secret_dev_key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
# Recommended settings for SQLAlchemy
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = False # Set to True for debugging SQL queries

# --- Extensions Initialization ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login' # Redirect to 'login' route if @login_required fails
login_manager.login_message_category = 'info' # Flash message category

# --- Adzuna & AI Configuration ---
ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID')
ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY')
ADZUNA_API_BASE_URL = 'https://api.adzuna.com/v1/api/jobs'
RESULTS_PER_PAGE = 20
AZURE_AI_ENDPOINT = os.getenv('AZURE_AI_ENDPOINT')
AZURE_AI_KEY = os.getenv('AZURE_AI_KEY')

# --- Database Models ---

# User Model implementing UserMixin for Flask-Login compatibility
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    saved_jobs = db.relationship('SavedJob', backref='user', lazy=True, cascade="all, delete-orphan") # Relationship

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.email}>'

# SavedJob Model
class SavedJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    adzuna_job_id = db.Column(db.String(100), nullable=False) # Store Adzuna's unique ID
    title = db.Column(db.String(200), nullable=False)
    company = db.Column(db.String(150))
    location = db.Column(db.String(150))
    adzuna_url = db.Column(db.String(500)) # Store the Adzuna redirect URL
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Ensure a user cannot save the same job twice
    __table_args__ = (db.UniqueConstraint('user_id', 'adzuna_job_id', name='_user_job_uc'),)

    def __repr__(self):
        return f'<SavedJob {self.title} ({self.adzuna_job_id})>'

# --- Flask-Login User Loader ---
@login_manager.user_loader
def load_user(user_id):
    """Callback used by Flask-Login to reload the user object from the user ID stored in the session."""
    return User.query.get(int(user_id))

# --- Forms (using Flask-WTF) ---

class RegistrationForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password', message='Passwords must match.')])
    submit = SubmitField('Register')

    # Custom validator to check if email already exists
    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('That email is already taken. Please choose a different one or login.')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

# --- Helper Functions (Adzuna, AI) ---

def get_salary_histogram(country_code, location, job_title):
    """ Fetches salary histogram data from Adzuna. (Unchanged) """
    # ... (keep existing function code) ...
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY: return None
    histogram_url = f"{ADZUNA_API_BASE_URL}/{country_code.lower()}/histogram"
    params = { 'app_id': ADZUNA_APP_ID, 'app_key': ADZUNA_APP_KEY, 'location0': location, 'what': job_title, 'content-type': 'application/json' }
    app.logger.info(f"Fetching salary histogram for: {params}")
    try:
        response = requests.get(histogram_url, params=params, timeout=15); response.raise_for_status(); data = response.json()
        if 'histogram' in data and data['histogram']:
            app.logger.info("Successfully fetched salary histogram.")
            total_salary = 0; total_count = 0
            for salary_point, count in data['histogram'].items():
                try: total_salary += float(salary_point) * count; total_count += count
                except ValueError: continue
            average_salary = round(total_salary / total_count) if total_count > 0 else None
            return {"histogram": data['histogram'], "average": average_salary}
        else: app.logger.info("No salary histogram data found."); return None
    except Exception as e: app.logger.error(f"Error fetching salary histogram: {e}"); return None


def get_ai_summary(query_details, total_jobs, job_listings_sample, salary_data):
    """ Calls Azure AI model for an enhanced recruiter-focused summary. (Unchanged) """
    # ... (keep existing function code) ...
    if not AZURE_AI_ENDPOINT or not AZURE_AI_KEY: return None
    sample_titles = [job['title'] for job in job_listings_sample[:7]]
    sample_descriptions = " ".join([job['description'] for job in job_listings_sample[:5] if isinstance(job.get('description'), str)])
    max_desc_length = 1000
    if len(sample_descriptions) > max_desc_length: sample_descriptions = sample_descriptions[:max_desc_length] + "..."
    salary_info = "Not available"
    if salary_data and salary_data.get('average'): salary_info = f"approximately {salary_data['average']:,} (currency based on country)"
    elif salary_data and salary_data.get('histogram'): salary_info = "Distribution data available, but average could not be calculated."
    system_message = ("You are an AI assistant providing recruitment market analysis. Focus on actionable insights for a recruiter based *only* on the provided data. Use Markdown for formatting (like **bold**).")
    user_prompt = ( f"Analyze the job market for a recruiter hiring for '{query_details['what']}' in '{query_details['where']}, {query_details['country'].upper()}'.\n\n**Market Data:**\n- Total Job Listings Found: {total_jobs}\n- Estimated Average Salary: {salary_info}\n- Sample Job Titles: {', '.join(sample_titles) if sample_titles else 'N/A'}\n- Sample Job Description Excerpts: {sample_descriptions if sample_descriptions else 'N/A'}\n\n**Recruiter Analysis (Based *only* on above data - use Markdown for emphasis):**\n1.  **Market Activity & Competitiveness:** Based on job volume and salary data (if available), how active/competitive does this market seem?\n2.  **Key Skills/Keywords:** Based *only* on the sample titles and descriptions, what 2-3 potential key skills or technologies seem commonly required?\n3.  **Candidate Pool & Sourcing:** What does the job volume suggest about the likely candidate pool size and the potential need for proactive sourcing vs. relying on applications?\n\nProvide a concise, bulleted summary. Do not invent skills or salary details not present in the data." )
    payload = { "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": user_prompt}], "max_tokens": 250, "temperature": 0.5 }
    headers = { 'Content-Type': 'application/json', 'api-key': AZURE_AI_KEY }
    app.logger.info(f"Sending enhanced recruiter request to Azure AI Endpoint: {AZURE_AI_ENDPOINT}")
    try:
        response = requests.post(AZURE_AI_ENDPOINT, headers=headers, json=payload, timeout=30); response.raise_for_status(); response_data = response.json()
        if 'choices' in response_data and len(response_data['choices']) > 0:
            message = response_data['choices'][0].get('message')
            if message and 'content' in message: return message['content'].strip()
            else: app.logger.warning(f"Azure AI response 'choices' structure unexpected: {message}"); return None
        else: app.logger.warning(f"Azure AI response did not contain 'choices'. Response: {response_data}"); return None
    except Exception as e: app.logger.error(f"Error calling Azure AI endpoint: {e}"); flash(f"Could not generate AI summary: Error communicating with the AI service.", "warning"); return None


def extract_adzuna_job_id(url):
    """Extracts the Adzuna job ID from the redirect URL."""
    try:
        parsed_url = urlparse(url)
        # Adzuna job ID is often the last path component before query params
        path_parts = parsed_url.path.strip('/').split('/')
        if path_parts:
            # Check if the last part looks like a job ID (often numeric or alphanumeric)
            potential_id = path_parts[-1]
            # Basic check: adjust if Adzuna ID format is different
            if potential_id.isalnum() and len(potential_id) > 5:
                 return potential_id
        # Fallback: Check query parameters (less common for ID)
        query_params = parse_qs(parsed_url.query)
        if 'jobId' in query_params: return query_params['jobId'][0]
        if 'id' in query_params: return query_params['id'][0]

    except Exception as e:
        app.logger.error(f"Error parsing Adzuna URL {url}: {e}")
    return None # Return None if ID cannot be reliably extracted


# --- Routes ---

@app.route('/')
def home():
    """ Renders the main search page. """
    # Get saved job IDs for the current user to mark jobs as saved in the results
    saved_job_ids = set()
    if current_user.is_authenticated:
        saved_job_ids = {job.adzuna_job_id for job in current_user.saved_jobs}

    # Pass saved_job_ids to the template if needed immediately (or handle in /insights)
    return render_template('index.html', insights=None, form_data={}, saved_job_ids=saved_job_ids)

@app.route('/insights', methods=['POST'])
def get_insights():
    """ Handles search form submission, fetches data, gets AI summary, renders results. """
    job_title = request.form.get('what')
    location = request.form.get('where')
    country_code = request.form.get('country')
    form_data = {'what': job_title, 'where': location, 'country': country_code}

    if not all([job_title, location, country_code]):
        flash("Please fill in all fields.", "error")
        return render_template('index.html', insights=None, form_data=form_data, saved_job_ids=set())

    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
         flash("Adzuna API credentials not configured.", "error")
         return render_template('index.html', insights=None, form_data=form_data, saved_job_ids=set())

    insights_data = None
    salary_data = None
    ai_summary_raw = None

    # --- Call Adzuna Search API ---
    api_url = f"{ADZUNA_API_BASE_URL}/{country_code.lower()}/search/1"
    params = { 'app_id': ADZUNA_APP_ID, 'app_key': ADZUNA_APP_KEY, 'what': job_title, 'where': location, 'results_per_page': RESULTS_PER_PAGE, 'content-type': 'application/json' }
    try:
        app.logger.info(f"Fetching Adzuna data for: {params}")
        response = requests.get(api_url, params=params, timeout=20); response.raise_for_status(); data = response.json()
        app.logger.info("Successfully fetched data from Adzuna.")

        total_jobs = data.get('count', 0)
        results = data.get('results', [])
        job_listings = []
        for job in results:
            adzuna_url = job.get('redirect_url')
            adzuna_job_id = extract_adzuna_job_id(adzuna_url) if adzuna_url else None
            if adzuna_job_id: # Only include jobs where we could extract an ID
                job_listings.append({
                    "adzuna_job_id": adzuna_job_id, # Add the extracted ID
                    "title": job.get('title'), "company": job.get('company', {}).get('display_name', 'N/A'),
                    "location": job.get('location', {}).get('display_name', 'N/A'),
                    "description": job.get('description', 'No description available.'),
                    "url": adzuna_url, "created": job.get('created')
                })

        insights_data = {
            "query": form_data, "total_matching_jobs": total_jobs,
            "job_listings": job_listings, "ai_summary_html": None, "salary_data": None
        }

        # --- Call Adzuna Histogram & Azure AI (if search successful) ---
        if insights_data:
            salary_data = get_salary_histogram(country_code, location, job_title)
            if salary_data: insights_data['salary_data'] = salary_data

            ai_summary_raw = get_ai_summary( insights_data['query'], insights_data['total_matching_jobs'], insights_data['job_listings'][:10], salary_data )
            if ai_summary_raw:
                html_summary = markdown.markdown(ai_summary_raw, extensions=['fenced_code'])
                insights_data['ai_summary_html'] = Markup(html_summary)

    # --- Error Handling (Simplified) ---
    except requests.exceptions.Timeout: flash("Adzuna request timed out.", "error")
    except requests.exceptions.HTTPError as e: flash(f"Adzuna API Error: {e.response.status_code}.", "error")
    except requests.exceptions.RequestException: flash("Adzuna connection error.", "error")
    except Exception as e: app.logger.error(f"Unexpected error: {e}"); flash("An internal server error occurred.", "error")

    # Get saved job IDs for the current user to mark jobs as saved
    saved_job_ids = set()
    if current_user.is_authenticated:
        saved_job_ids = {job.adzuna_job_id for job in current_user.saved_jobs}

    return render_template('index.html', insights=insights_data, form_data=form_data, saved_job_ids=saved_job_ids)


# --- Authentication Routes ---

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
        db.session.commit()
        flash('Congratulations, you are now a registered user! Please login.', 'success')
        app.logger.info(f"New user registered: {form.email.data}")
        return redirect(url_for('login'))
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
            return redirect(url_for('login'))
        # Log the user in
        login_user(user, remember=True) # Add 'remember=True' if you want "remember me" functionality
        flash(f'Welcome back, {user.email}!', 'success')
        app.logger.info(f"User logged in: {user.email}")
        # Redirect to the page the user was trying to access, or home
        next_page = request.args.get('next')
        return redirect(next_page) if next_page else redirect(url_for('home'))
    return render_template('login.html', title='Login', form=form)

@app.route('/logout')
@login_required # Ensure user is logged in to logout
def logout():
    app.logger.info(f"User logged out: {current_user.email}")
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

# --- Saved Jobs Routes ---

@app.route('/save_job', methods=['POST'])
@login_required # Protect this route
def save_job():
    adzuna_job_id = request.form.get('adzuna_job_id')
    title = request.form.get('title')
    company = request.form.get('company')
    location = request.form.get('location')
    adzuna_url = request.form.get('adzuna_url')

    if not all([adzuna_job_id, title, adzuna_url]):
         flash('Missing job details to save.', 'error')
         return redirect(request.referrer or url_for('home')) # Redirect back

    # Check if already saved
    existing_save = SavedJob.query.filter_by(user_id=current_user.id, adzuna_job_id=adzuna_job_id).first()
    if existing_save:
        flash('Job already saved.', 'info')
    else:
        # Create and save the job
        saved_job = SavedJob(
            adzuna_job_id=adzuna_job_id,
            title=title,
            company=company,
            location=location,
            adzuna_url=adzuna_url,
            user_id=current_user.id
        )
        db.session.add(saved_job)
        try:
            db.session.commit()
            flash('Job saved successfully!', 'success')
            app.logger.info(f"User {current_user.id} saved job {adzuna_job_id}")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error saving job {adzuna_job_id} for user {current_user.id}: {e}")
            flash('Error saving job. Please try again.', 'error')
    referrer_url = request.referrer
    redirect_target = referrer_url or url_for('home')
    app.logger.info(f"Save successful. Referrer: '{referrer_url}'. Redirecting to: '{redirect_target}'")
    # --- End Logging ---

    # Redirect back to the page the user came from
    return redirect(request.referrer or url_for('home'))


@app.route('/unsave_job', methods=['POST'])
@login_required # Protect this route
def unsave_job():
    adzuna_job_id = request.form.get('adzuna_job_id')
    if not adzuna_job_id:
        flash('Missing job ID to unsave.', 'error')
        return redirect(request.referrer or url_for('home'))

    job_to_unsave = SavedJob.query.filter_by(user_id=current_user.id, adzuna_job_id=adzuna_job_id).first()
    if job_to_unsave:
        db.session.delete(job_to_unsave)
        try:
            db.session.commit()
            flash('Job removed from saved list.', 'success')
            app.logger.info(f"User {current_user.id} unsaved job {adzuna_job_id}")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error unsaving job {adzuna_job_id} for user {current_user.id}: {e}")
            flash('Error unsaving job. Please try again.', 'error')
    else:
        flash('Job not found in your saved list.', 'warning')

    # Redirect back to the page the user came from
    return redirect(request.referrer or url_for('home'))


@app.route('/saved_jobs')
@login_required # Protect this route
def saved_jobs_list():
    """Displays the list of jobs saved by the current user."""
    jobs = SavedJob.query.filter_by(user_id=current_user.id).order_by(SavedJob.id.desc()).all()
    return render_template('saved_jobs.html', title='Saved Jobs', jobs=jobs)


# --- Main execution ---
if __name__ == '__main__':
    # Create database tables if they don't exist (useful for initial local setup)
    # For production, rely on Flask-Migrate
    with app.app_context():
         # db.create_all() # Comment out after first run or when using migrations
         pass
    app.run(host='0.0.0.0', port=5000, debug=False) # debug=False for production
