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
    # It will automatically use the DIGITALOCEAN_TOKEN environment variable
    # set in your Terraform Cloud workspace.
    provider "digitalocean" {
      # No explicit token needed here when DIGITALOCEAN_TOKEN is set in TFC environment
    }
    