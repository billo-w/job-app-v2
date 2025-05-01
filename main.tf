# Configure the DigitalOcean Provider
terraform {
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}

# --- Variables ---
# Defined in variables.tf

variable "do_token" {
  description = "DigitalOcean API Token"
  type        = string
  sensitive   = true
}

variable "repo_path" {
  description = "GitHub repository path (e.g., your_username/your_repo_name)"
  type        = string
}

variable "app_name" {
  description = "Name for the App Platform app"
  type        = string
  default     = "job-app"
}

variable "app_region" {
  description = "Region for the app"
  type        = string
  default     = "lon1" # e.g., London
}

variable "production_branch" {
  description = "The GitHub branch to deploy to production"
  type        = string
  default     = "production"
}

variable "database_url_prod" {
  description = "Connection string (DATABASE_URL) for the production database (must be created separately)"
  type        = string
  sensitive   = true
}

variable "flask_secret_key_prod" {
  description = "Flask secret key for production"
  type        = string
  sensitive   = true
}
variable "adzuna_app_id" {
  description = "Adzuna App ID"
  type        = string
  sensitive   = true
}
variable "adzuna_app_key" {
  description = "Adzuna App Key"
  type        = string
  sensitive   = true
}
variable "azure_ai_endpoint" {
  description = "Azure AI Endpoint URL"
  type        = string
  sensitive   = true
}
variable "azure_ai_key" {
  description = "Azure AI Key"
  type        = string
  sensitive   = true
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

    # Define the Web Service (your Flask app)
    service {
      name = "${var.app_name}-service" # Name for the service component

      # --- CORRECTED: github block INSIDE service ---
      github {
        repo             = var.repo_path
        branch           = var.production_branch
        deploy_on_push = true # Automatically deploy on push to the branch
      }

      instance_size_slug = "basic-xxs" # Choose instance size
      instance_count     = 1          # Number of instances

      # Define Environment Variables (Correctly placed inside service)
      environment_vars = [
        {
          key   = "FLASK_APP"
          # If using factory via wsgi.py: value = "wsgi:application"
          # If using factory directly: value = "app:create_app()"
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

      # Define the run command (Correctly placed inside service)
      run_command = "gunicorn 'app:create_app()' --bind 0.0.0.0:$PORT --workers 2 --log-level info"

      # Define the build command (if needed, often auto-detected for Python)
      # build_command = "pip install -r requirements.txt" # Example if needed

      # Define health checks (Correctly placed inside service)
      health_check {
        http_path = "/" # Path for HTTP health check (e.g., your home route)
      }
    }
    # Database block removed
    # Migration job block removed
  }
}

# --- Outputs ---
# Output the App's default ingress URL
output "app_url" {
  value = digitalocean_app.jobapp.default_ingress
}
