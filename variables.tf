variable "droplet_name" {
  description = "Name for the Droplet"
  type        = string
}

variable "droplet_region" {
  description = "Region for the Droplet"
  type        = string
}

variable "droplet_size" {
  description = "Size slug for the Droplet"
  type        = string
}

variable "droplet_image" {
  description = "Image slug for the Droplet OS"
  type        = string
}

variable "ssh_key_name" {
  description = "The name of your SSH key as it appears in your DigitalOcean account (used for initial Droplet access)"
  type        = string
}
variable "deployment_ssh_public_key" {
  description = "The public SSH key (e.g., content of id_ed25519.pub) for the 'billo' user, used by CI/CD for deployment."
  type        = string
}

variable "app_user_name" {
  description = "The username for the application (e.g., billo)"
  type        = string
  default     = "billo"
}

variable "cloud_firewall_name" {
  description = "The name of your existing DigitalOcean Cloud Firewall to assign to the Droplet."
  type        = string
}