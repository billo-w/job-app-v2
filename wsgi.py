# wsgi.py
import os
from dotenv import load_dotenv

# Load environment variables BEFORE creating the app
# Ensures DATABASE_URL etc. are available when create_app runs
load_dotenv()

# Import the factory function from your main application file
from app import create_app

# Call the factory function to create the app instance
# This 'application' variable is what Gunicorn often looks for by default
application = create_app()

# Optional: Add a check for running directly (less common for wsgi.py)
# if __name__ == "__main__":
#    application.run()