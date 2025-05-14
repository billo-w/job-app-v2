# providers.tf
terraform {
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.30" # Or your compatible version
    }
  }
}

# Configure the DigitalOcean provider itself
provider "digitalocean" {
  # The token can be implicitly picked up from the DO_TOKEN env var
  # or explicitly set via var.do_token if you prefer.
  # If using TFC, it's better to set DO_TOKEN as an Environment Variable in the TFC workspace.
  # If var.do_token is defined and you want to use it:
  token = var.do_token
}
