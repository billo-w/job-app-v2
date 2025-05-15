# backend.tf
terraform {
  cloud {
    organization = "<YOUR_TFC_ORG_NAME>" # Keep your organization name
    workspaces {
      name = "<YOUR_NEW_WORKSPACE_NAME>" # UPDATE THIS LINE
    }
  }
}
