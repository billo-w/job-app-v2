# tests/test_app.py
from app import app # Import your Flask app instance

def test_home_page():
    """Test if the home page loads."""
    # Create a test client
    client = app.test_client()
    # Make a GET request to the home page
    response = client.get('/')
    # Assert that the response status code is 200 (OK)
    assert response.status_code == 200
    # Assert that some expected text is in the response
    assert b"Recruiter Job Market Insights" in response.data

# Add more tests for login page, registration, etc.
