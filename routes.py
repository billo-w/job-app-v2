from flask import (Blueprint, render_template, request, flash, redirect, url_for,
                   jsonify, current_app) # Import current_app for logger
from flask_login import login_required, current_user, login_user, logout_user
import logging
from urllib.parse import urlparse, urlunparse # Added urlunparse

# Import necessary components from your main module (or models/forms files if separated)
# Assuming app.py structure where these are defined or imported
from app import db, User, SavedJob, RegistrationForm, LoginForm
from app import fetch_market_insights # Import the main data fetching helper

# Create a Blueprint
main_bp = Blueprint('main_bp', __name__)

# Get logger instance
logger = logging.getLogger(__name__)

# --- Main Routes ---
@main_bp.route('/')
def home():
    """ Renders the main search page or results based on GET parameters. """
    what = request.args.get('what', '')
    where = request.args.get('where', '')
    country = request.args.get('country', '')
    # Get the summary flag, default to 'true' if not present or doing initial load
    generate_summary_flag = request.args.get('generate_summary', 'true') == 'true'

    form_data = {
        'what': what,
        'where': where,
        'country': country,
        'generate_summary': 'true' if generate_summary_flag else 'false' # Keep for form pre-fill
    }

    insights_data = None
    saved_job_ids = set()

    if what and where and country:
        logger.info(f"Home route received search parameters: {form_data}")
        # Pass the boolean flag to the fetch function
        insights_data = fetch_market_insights(what, where, country, generate_summary=generate_summary_flag)

    if current_user.is_authenticated:
        saved_job_ids = {job.adzuna_job_id for job in current_user.saved_jobs}

    return render_template('index.html',
                           insights=insights_data,
                           form_data=form_data, # Pass form_data to pre-fill search boxes & checkbox
                           saved_job_ids=saved_job_ids)


@main_bp.route('/insights', methods=['POST'])
def get_insights():
    """ Handles the POST from the search form (PRG Pattern). """
    what = request.form.get('what')
    where = request.form.get('where')
    country = request.form.get('country')
    # Check if the checkbox was checked - its value will be 'true' if checked, None otherwise
    generate_summary = 'true' if request.form.get('generate_summary') == 'true' else 'false'

    if not all([what, where, country]):
        flash("Please fill in all search fields.", "error")
        return redirect(url_for('main_bp.home')) # Use blueprint name

    # Redirect to the home route with parameters in the query string
    return redirect(url_for('main_bp.home',
                            what=what,
                            where=where,
                            country=country,
                            generate_summary=generate_summary)) # Pass summary flag


# --- Authentication Routes ---
@main_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main_bp.home'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        try:
            db.session.commit()
            flash('Congratulations, you are now a registered user! Please login.', 'success')
            logger.info(f"New user registered: {form.email.data}")
            return redirect(url_for('main_bp.login'))
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error registering user {form.email.data}: {e}")
            flash('An error occurred during registration. Please try again.', 'error')
    return render_template('register.html', title='Register', form=form)


@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main_bp.home'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid email or password.', 'error')
        else:
            login_user(user, remember=form.remember.data)
            flash(f'Welcome back, {user.email}!', 'success')
            logger.info(f"User logged in: {user.email}")
            next_page = request.args.get('next')
            # Use url_for with blueprint name for internal redirect check
            safe_next_page = url_for('main_bp.home') # Default redirect
            if next_page:
                # Basic security check: Ensure it's a relative path within the app
                # Avoid redirecting to external URLs
                target = urlparse(next_page)
                if not target.netloc and target.path:
                    safe_next_page = next_page
                    logger.info(f"Redirecting logged in user to: {safe_next_page}")
                else:
                    logger.warning(f"Ignoring potentially unsafe next_page: {next_page}")
            else:
                 logger.info("Redirecting logged in user to home.")

            return redirect(safe_next_page)
    return render_template('login.html', title='Login', form=form)


@main_bp.route('/logout')
@login_required
def logout():
    logger.info(f"User logged out: {current_user.email}")
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('main_bp.home'))


# --- Saved Jobs Routes ---
@main_bp.route('/save_job', methods=['POST'])
@login_required
def save_job():
    """Handles AJAX request to save a job."""
    if not request.is_json:
        logger.warning("Received non-JSON POST request to /save_job")
        return jsonify({'status': 'error', 'message': 'Unsupported request format.'}), 415

    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'Invalid JSON request.'}), 400

    adzuna_job_id = data.get('adzuna_job_id')
    title = data.get('title')
    company = data.get('company')
    location = data.get('location')
    adzuna_url = data.get('adzuna_url')

    if not all([adzuna_job_id, title, adzuna_url]):
        return jsonify({'status': 'error', 'message': 'Missing job details.'}), 400

    existing_save = SavedJob.query.filter_by(user_id=current_user.id, adzuna_job_id=adzuna_job_id).first()
    if existing_save:
        return jsonify({'status': 'error', 'message': 'Job already saved.'}), 409

    saved_job = SavedJob(
        adzuna_job_id=adzuna_job_id, title=title, company=company,
        location=location, adzuna_url=adzuna_url, user_id=current_user.id
    )
    db.session.add(saved_job)
    try:
        db.session.commit()
        logger.info(f"User {current_user.id} saved job {adzuna_job_id} via AJAX")
        return jsonify({'status': 'success', 'message': 'Job saved!'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error saving job {adzuna_job_id} for user {current_user.id} via AJAX: {e}")
        return jsonify({'status': 'error', 'message': 'Database error saving job.'}), 500


@main_bp.route('/unsave_job', methods=['POST'])
@login_required
def unsave_job():
    """ Handles both AJAX and standard form POST requests to unsave a job. """
    is_ajax = False
    adzuna_job_id = None

    if request.is_json:
        is_ajax = True
        data = request.get_json()
        if not data: return jsonify({'status': 'error', 'message': 'Invalid JSON request.'}), 400
        adzuna_job_id = data.get('adzuna_job_id')
        logger.info(f"Received AJAX unsave request for job ID: {adzuna_job_id}")
    elif request.form:
        adzuna_job_id = request.form.get('adzuna_job_id')
        logger.info(f"Received Form unsave request for job ID: {adzuna_job_id}")
    else:
        logger.error("Unsave request received without valid JSON or Form data.")
        return "Unsupported Media Type", 415

    if not adzuna_job_id:
        message = 'Missing job ID.'
        if is_ajax: return jsonify({'status': 'error', 'message': message}), 400
        else: flash(message, 'error'); return redirect(url_for('main_bp.saved_jobs_list'))

    job_to_unsave = SavedJob.query.filter_by(user_id=current_user.id, adzuna_job_id=adzuna_job_id).first()

    if job_to_unsave:
        db.session.delete(job_to_unsave)
        try:
            db.session.commit()
            message = 'Job removed from saved list.'
            logger.info(f"User {current_user.id} unsaved job {adzuna_job_id}")
            if is_ajax: return jsonify({'status': 'success', 'message': message})
            else: flash(message, 'success'); return redirect(url_for('main_bp.saved_jobs_list'))
        except Exception as e:
            db.session.rollback()
            message = 'Database error unsaving job.'
            logger.error(f"Error unsaving job {adzuna_job_id} for user {current_user.id}: {e}")
            if is_ajax: return jsonify({'status': 'error', 'message': message}), 500
            else: flash(message, 'error'); return redirect(url_for('main_bp.saved_jobs_list'))
    else:
        message = 'Job not found in your saved list.'
        logger.warning(f"Attempt to unsave non-existent/already unsaved job {adzuna_job_id} for user {current_user.id}")
        if is_ajax: return jsonify({'status': 'error', 'message': message}), 404
        else: flash(message, 'warning'); return redirect(url_for('main_bp.saved_jobs_list'))


@main_bp.route('/saved_jobs')
@login_required
def saved_jobs_list():
    """ Displays the list of jobs saved by the current user. """
    jobs = SavedJob.query.filter_by(user_id=current_user.id).order_by(SavedJob.id.desc()).all()
    return render_template('saved_jobs.html', title='Saved Jobs', jobs=jobs)

