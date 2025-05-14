# Data source to look up your existing SSH key by its name
data "digitalocean_ssh_key" "app_ssh_key" {
  name = var.ssh_key_name # This name must match the name in your DO account
}

# Define the DigitalOcean Droplet Resource
resource "digitalocean_droplet" "job_app_server" {
  name    = var.droplet_name
  region  = var.droplet_region
  size    = var.droplet_size
  image   = var.droplet_image

  # Associate the SSH key using its ID looked up via the data source
  # This assumes the key is already added to your DigitalOcean account
  ssh_keys = [data.digitalocean_ssh_key.app_ssh_key.id]

  # Optional: Add tags if your existing Droplet has them
  # tags = ["web", "flask", "job-app"]

  # Optional: If you manage a firewall with Terraform and want to associate it
  # firewall_id = digitalocean_firewall.your_firewall_resource_name.id

  # Note: user_data for cloud-init is typically for initial setup.
  # Since the Droplet exists, we usually don't re-apply user_data unless intended.
}

# Output the Droplet's IP address
output "droplet_ip_address" {
  description = "The public IPv4 address of the Droplet."
  value       = digitalocean_droplet.job_app_server.ipv4_address
}
