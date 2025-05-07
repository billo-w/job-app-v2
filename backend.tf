# backend.tf
terraform {
  cloud {
    organization = "<YOUR_ORG_NAME>"
    workspaces {
      name = "<YOUR_WORKSPACE_NAME>"
    }
  }
}