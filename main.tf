# Configure the DigitalOcean Provider
terraform {
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}

# --- Provider Configuration ---
provider "digitalocean" {
  token = var.do_token
}

# --- DigitalOcean App Platform App Resource ---
resource "digitalocean_app" "jobapp" {
  spec {
    name   = var.app_name
    region = var.app_region

    # Link to your GitHub repository
    github {
      repo             = var.repo_path
      branch           = var.production_branch
      deploy_on_push = true # Automatically deploy on push to the branch
    }

    # Define the Web Service (your Flask app)
    service {
      name = "${var.app_name}-service" # Name for the service component
      instance_size_slug = "basic-xxs" # Choose instance size
      instance_count     = 1          # Number of instances

      # Define Environment Variables
      environment_vars = [
        {
          key   = "FLASK_APP"
          value = "app:create_app()" # Match run command
        },
        {
          key   = "FLASK_ENV"
          value = "production"
        },
        {
          key   = "DATABASE_URL"
          value = var.database_url_prod # Get connection string from variable
          type  = "SECRET"              # Mark as secret
        },
        {
          key   = "FLASK_SECRET_KEY"
          value = var.flask_secret_key_prod
          type  = "SECRET"
        },
        {
          key   = "ADZUNA_APP_ID"
          value = var.adzuna_app_id
          type  = "SECRET"
        },
        {
          key   = "ADZUNA_APP_KEY"
          value = var.adzuna_app_key
          type  = "SECRET"
        },
        {
          key   = "AZURE_AI_ENDPOINT"
          value = var.azure_ai_endpoint
          type  = "SECRET"
        },
        {
          key   = "AZURE_AI_KEY"
          value = var.azure_ai_key
          type  = "SECRET"
        },
        # Add any other necessary environment variables
      ]

      # Define the run command (Gunicorn is recommended for production)
      run_command = "gunicorn 'app:create_app()' --bind 0.0.0.0:$PORT --workers 2 --log-level info"

      # Define the build command (if needed, often auto-detected for Python)
      # build_command = "pip install -r requirements.txt" # Example if needed

      # Define health checks (optional but recommended)
      health_check {
        http_path = "/" # Path for HTTP health check (e.g., your home route)
      }
    }
    # Removed database block
    # Removed job block (migration job) - Migrations need to be run manually or via a different process
  }
}

# --- Outputs ---
# Output the App's default ingress URL
output "app_url" {
  value = digitalocean_app.jobapp.default_ingress
}
