variable "do_token" {
  description = "DigitalOcean API Token"
  type        = string
  sensitive   = true
}

variable "droplet_name" {
  description = "Name for the Droplet"
  type        = string
  default     = "job-app-server" # Change to your actual Droplet name
}

variable "droplet_region" {
  description = "Region for the Droplet"
  type        = string
  default     = "lon1" # Change to your actual Droplet region
}

variable "droplet_size" {
  description = "Size slug for the Droplet"
  type        = string
  default     = "s-1vcpu-1gb" # Change to your actual Droplet size slug
}

variable "droplet_image" {
  description = "Image slug for the Droplet OS"
  type        = string
  default     = "ubuntu-22-04-x64" # Change to your actual Droplet image
}

variable "ssh_key_name" {
  description = "The name of your SSH key as it appears in your DigitalOcean account"
  type        = string
  default     = "github_deploy_key"
  # You will provide the actual value via Terraform Cloud variables or a .tfvars file
}
