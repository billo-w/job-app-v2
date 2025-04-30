import pytest
import os
# Import the factory function and db instance
from app import create_app, db

# Define a test configuration class
class TestConfig:
    TESTING = True
    # Use environment variable for test DB, fallback to local default
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'TEST_DATABASE_URL',
        'postgresql://testuser:testpassword@localhost:5432/jobapp_testdb' # Match CI service DB
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False # Disable CSRF for testing forms
    LOGIN_DISABLED = True # Optional: Disable login checks for certain tests
    SECRET_KEY = 'test-secret-key' # Use a specific test secret key


@pytest.fixture(scope='module')
def test_app():
    """Create and configure a new app instance for each test module."""
    # Create app with test config
    app = create_app(TestConfig)

    # Establish an application context
    with app.app_context():
        # Create tables if the test DB is ephemeral (like in CI)
        db.create_all()
        yield app # provide the app object to tests that need it
        # Clean up
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope='module')
def client(test_app):
    """A test client for the app."""
    return test_app.test_client()


# --- Example Tests ---

def test_home_page_loads(client):
    """Test if the home page loads successfully (GET request)."""
    response = client.get('/') # Use url_for('main_bp.home') if using blueprint prefix
    assert response.status_code == 200
    assert b"Recruiter Job Market Insights" in response.data

def test_login_page_loads(client):
    """Test if the login page loads successfully."""
    response = client.get('/login') # Use url_for('main_bp.login')
    assert response.status_code == 200
    assert b"Welcome Back!" in response.data

def test_register_page_loads(client):
    """Test if the register page loads successfully."""
    response = client.get('/register') # Use url_for('main_bp.register')
    assert response.status_code == 200
    assert b"Register New Account" in response.data

# Add more tests...

