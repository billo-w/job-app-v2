# backend.tf
terraform {
  cloud {
    organization = "Belal_Waw" 
    workspaces {
      name = "job-app-production-remote" 
    }
  }
}
