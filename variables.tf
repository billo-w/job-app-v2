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
