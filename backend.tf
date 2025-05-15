# backend.tf
terraform {
  cloud {
    organization = "Belal_Waw" # Keep your organization name
    workspaces {
      name = "job-app-v2" # UPDATE THIS LINE
    }
  }
}
