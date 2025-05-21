variable "do_token" {
  description = "DigitalOcean API Token (Value should be set in Terraform Cloud as DIGITALOCEAN_TOKEN environment variable)"
  type        = string
  sensitive   = true
  # No default, as provider will use environment variable
}

variable "droplet_name" {
  description = "Name for the Droplet"
  type        = string
  default     = "job-app-server-tf"
}

variable "droplet_region" {
  description = "Region for the Droplet"
  type        = string
  default     = "lon1" # e.g., London
}

variable "droplet_size" {
  description = "Size slug for the Droplet"
  type        = string
  default     = "s-1vcpu-1gb" # Example: Basic Droplet
}

variable "droplet_image" {
  description = "Image slug for the Droplet OS"
  type        = string
  default     = "ubuntu-22-04-x64"
}

variable "ssh_key_name_for_root" {
  description = "The name of your SSH key in DO for initial root access to the Droplet. Value set in Terraform Cloud."
  type        = string
  # No default, value must be provided in Terraform Cloud
}

variable "deployment_ssh_public_key" {
  description = "The public SSH key (e.g., content of id_ed25519.pub) for the app user, used by CI/CD for deployment. Value set in Terraform Cloud."
  type        = string
  sensitive   = true # Public key itself isn't secret, but treat as sensitive if passing full content
  # No default, value must be provided in Terraform Cloud
}

variable "app_user_name" {
  description = "The username for the application (e.g., billo)"
  type        = string
  default     = "billo"
}

variable "cloud_firewall_id" {
  description = "The id of your existing DigitalOcean Cloud Firewall to assign to the Droplet. Value set in Terraform Cloud."
  type        = string
  # No default, value must be provided in Terraform Cloud
}

variable "existing_reserved_ip_address" {
  description = "The IP address string of the existing DigitalOcean Reserved IP to assign to the Droplet. Value set in Terraform Cloud."
  type        = string
  # No default, value must be provided in Terraform Cloud
  # Example: "192.0.2.123"
}

# Variables for application environment variables (values set in Terraform Cloud)
variable "repo_path" {
  description = "GitHub repository path (e.g., your_username/your_repo_name)"
  type        = string
}

variable "database_url_prod" {
  description = "Connection string (DATABASE_URL) for the production database"
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
