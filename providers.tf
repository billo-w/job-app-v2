    # providers.tf
    terraform {
      cloud {
        organization = "<YOUR_TFC_ORG_NAME>" # Replace with your Terraform Cloud organization
        workspaces {
          name = "<YOUR_TFC_WORKSPACE_NAME_FOR_DROPLET>" # e.g., "job-app-droplet-prod"
        }
      }
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
    