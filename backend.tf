# backend.tf
terraform {
  cloud {
    organization = "Belal_Waw"
    workspaces {
      name = "digitalocean-flask-app"
    }
  }
}