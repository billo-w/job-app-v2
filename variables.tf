variable "droplet_name" {
  description = "Name for the Droplet"
  type        = string
  default     = "job-app-server-tf" # Consider a slightly different name to avoid old conflicts
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

variable "ssh_key_name" {
  description = "The name of your SSH key as it appears in your DigitalOcean account (used for initial Droplet access)"
  type        = string
  # Example: default = "My MacBook Pro Key" - Provide this in Terraform Cloud
}
