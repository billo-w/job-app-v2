# --- Variables ---
# You would typically define these in variables.tf and supply values via .tfvars or environment variables

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

# Add variables for other secrets as needed
variable "flask_secret_key_prod" {
  description = "Flask secret key for production" # Optional description
  type        = string
  sensitive   = true
}
variable "adzuna_app_id" {
  description = "Adzuna App ID" # Optional description
  type        = string
  sensitive   = true
}
variable "adzuna_app_key" {
  description = "Adzuna App Key" # Optional description
  type        = string
  sensitive   = true
}
variable "azure_ai_endpoint" {
  description = "Azure AI Endpoint URL" # Optional description
  type        = string
  sensitive   = true
}
variable "azure_ai_key" {
  description = "Azure AI Key" # Optional description
  type        = string
  sensitive   = true
}
