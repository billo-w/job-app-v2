# main.tf

# Data source to look up your existing SSH key by its name for root access
data "digitalocean_ssh_key" "initial_root_ssh_key" {
  name = var.ssh_key_name_for_root
}

# --- Data source to look up an EXISTING Reserved IP by its address ---
data "digitalocean_reserved_ip" "existing_job_app_ip" {
  ip_address = var.existing_reserved_ip_address
}

# Define the DigitalOcean Droplet Resource
resource "digitalocean_droplet" "job_app_server" {
  name    = var.droplet_name
  region  = var.droplet_region
  size    = var.droplet_size
  image   = var.droplet_image

  ssh_keys = [data.digitalocean_ssh_key.initial_root_ssh_key.id]
  monitoring = true

  user_data = <<-EOF
              #!/bin/bash
              set -e
              APP_USER="${var.app_user_name}"
              # --- CORRECTED VARIABLE REFERENCE ---
              DEPLOYMENT_PUBLIC_KEY="${var.ssh_public_key}"

              export DEBIAN_FRONTEND=noninteractive
              apt-get update -y
              apt-get upgrade -y
              apt-get install -y nginx python3 python3-pip python3-venv libpq-dev build-essential
              if ! id -u "$APP_USER" >/dev/null 2>&1; then
                  useradd -m -s /bin/bash "$APP_USER"
                  echo "$APP_USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/$APP_USER"
                  chmod 0440 "/etc/sudoers.d/$APP_USER"
              fi
              APP_USER_HOME="/home/$APP_USER"
              SSH_DIR="$APP_USER_HOME/.ssh"
              AUTH_KEYS_FILE="$SSH_DIR/authorized_keys"
              mkdir -p "$SSH_DIR"
              chown "$APP_USER:$APP_USER" "$APP_USER_HOME"
              chown "$APP_USER:$APP_USER" "$SSH_DIR"
              chmod 700 "$SSH_DIR"
              echo "$DEPLOYMENT_PUBLIC_KEY" > "$AUTH_KEYS_FILE" # This now uses var.ssh_public_key
              chown "$APP_USER:$APP_USER" "$AUTH_KEYS_FILE"
              chmod 600 "$AUTH_KEYS_FILE"
              systemctl enable nginx
              systemctl start nginx
              echo "User data script finished."
              EOF
}

# --- Assign an EXISTING Cloud Firewall to the Droplet ---
resource "digitalocean_firewall_assignment" "assign_firewall" {
  firewall_id  = var.cloud_firewall_id
  droplet_ids  = [digitalocean_droplet.job_app_server.id]
}

# --- Assign the EXISTING Reserved IP to the Droplet ---
resource "digitalocean_reserved_ip_assignment" "job_app_ip_assign" {
  ip_address = data.digitalocean_reserved_ip.existing_job_app_ip.ip_address
  droplet_id = digitalocean_droplet.job_app_server.id
}

# Output the (existing) Reserved IP address assigned to the Droplet
output "droplet_assigned_reserved_ip" {
  description = "The existing Reserved IP address assigned to the Droplet."
  value       = data.digitalocean_reserved_ip.existing_job_app_ip.ip_address
}

# Output the Droplet's current dynamic IP (can be useful for debugging, should match reserved IP after assignment)
output "droplet_dynamic_ip_address" {
  description = "The current dynamic public IPv4 address of the Droplet."
  value       = digitalocean_droplet.job_app_server.ipv4_address
}
