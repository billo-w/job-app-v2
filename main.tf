# Configure the DigitalOcean Provider
terraform {
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      # Keep constraint, but init uses the installed v2.52.0
      version = "~> 2.30" # Or your compatible version
    }
  }
}

# --- Variables ---
# Variable definitions are ONLY in variables.tf

# --- Provider Configuration ---
provider "digitalocean" {
  token = var.do_token # Value comes from variables.tf
}

# --- DigitalOcean App Platform App Resource ---
resource "digitalocean_app" "jobapp" {
  spec {
    name   = var.app_name   # Value comes from variables.tf
    region = var.app_region # Value comes from variables.tf

    # Define the Web Service (your Flask app)
    service {
      name = "${var.app_name}-service" # Name for the service component

      # --- github block INSIDE service ---
      github {
        repo             = var.repo_path           # Value comes from variables.tf
        branch           = var.production_branch # Value comes from variables.tf
        deploy_on_push = true                    # Automatically deploy on push to the branch
      }

      instance_size_slug = "basic-xxs" # Choose instance size
      instance_count     = 1          # Number of instances

      # --- Define multiple 'env' blocks with CORRECTED scope values ---
      env {
        key   = "FLASK_APP"
        value = "app:create_app()" # Match run command
        scope = "RUN_AND_BUILD_TIME"
      }
      env {
        key   = "FLASK_ENV"
        value = "production"
        scope = "RUN_AND_BUILD_TIME"
      }
      env {
        key   = "DATABASE_URL"
        value = var.database_url_prod # Value comes from variables.tf
        type  = "SECRET"
        scope = "RUN_AND_BUILD_TIME" # Needs to be available for build/migrations if applicable
      }
      env {
        key   = "FLASK_SECRET_KEY"
        value = var.flask_secret_key_prod # Value comes from variables.tf
        type  = "SECRET"
        scope = "RUN_TIME" # CORRECTED: Use RUN_TIME instead of RUN_TIME_ONLY
      }
      env {
        key   = "ADZUNA_APP_ID"
        value = var.adzuna_app_id # Value comes from variables.tf
        type  = "SECRET"
        scope = "RUN_TIME" # CORRECTED: Use RUN_TIME instead of RUN_TIME_ONLY
      }
      env {
        key   = "ADZUNA_APP_KEY"
        value = var.adzuna_app_key # Value comes from variables.tf
        type  = "SECRET"
        scope = "RUN_TIME" # CORRECTED: Use RUN_TIME instead of RUN_TIME_ONLY
      }
      env {
        key   = "AZURE_AI_ENDPOINT"
        value = var.azure_ai_endpoint # Value comes from variables.tf
        type  = "SECRET"
        scope = "RUN_TIME" # CORRECTED: Use RUN_TIME instead of RUN_TIME_ONLY
      }
      env {
        key   = "AZURE_AI_KEY"
        value = var.azure_ai_key # Value comes from variables.tf
        type  = "SECRET"
        scope = "RUN_TIME" # CORRECTED: Use RUN_TIME instead of RUN_TIME_ONLY
      }
      # Add other necessary env blocks here

      # Define the run command (Correctly placed inside service)
      run_command = "gunicorn 'app:create_app()' --bind 0.0.0.0:$PORT --workers 2 --log-level info"

      # Define the build command (if needed, often auto-detected for Python)
      # build_command = "pip install -r requirements.txt" # Example if needed

      # Define health checks (Correctly placed inside service)
      health_check {
        http_path = "/" # Path for HTTP health check (e.g., your home route)
      }
    } # End service block

    # --- ADDED: Migration Job ---
    job {
      name = "migration-job"
      kind = "PRE_DEPLOY" # Run before deploying the main service
      instance_size_slug = "basic-xxs" # Can use smaller instance for jobs

      # Source code for the job (usually same as service)
      github {
        repo             = var.repo_path
        branch           = var.production_branch
        deploy_on_push = true # Should match service setting
      }

      # Environment variables needed for the migration job
      # Inherits app-level vars, but explicitly define crucial ones
      env {
        key   = "DATABASE_URL"
        value = var.database_url_prod
        type  = "SECRET"
        scope = "RUN_AND_BUILD_TIME" # Needs DB URL at build/run time
      }
       env {
        key   = "FLASK_APP"
        value = "app:create_app()" # Needs to know how to load Flask context
        scope = "RUN_AND_BUILD_TIME"
      }
      # Add other envs if your migrations depend on them

      # Command to run migrations (apply existing migrations)
      # --- CORRECTED COMMAND ---
      run_command = "flask db upgrade"

      # Optional: Build command if different from service or needed explicitly
      # build_command = "pip install -r requirements.txt"
    } # End job block

  } # End spec block
} # End resource block

# --- Outputs ---
# Output the App's default ingress URL
output "app_url" {
  value = digitalocean_app.jobapp.default_ingress
}

