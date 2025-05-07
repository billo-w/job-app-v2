terraform {
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.30" # Or your compatible version
    }
  }
}

# Provider configuration (can also be here)
provider "digitalocean" {
  token = var.do_token # Value comes from variables.tf / environment
}