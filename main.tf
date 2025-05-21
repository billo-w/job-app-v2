# main.tf

# Data source to look up your existing SSH key by its name for root access
data "digitalocean_ssh_key" "initial_root_ssh_key" {
  name = var.ssh_key_name_for_root # This name must match an SSH key name in your DO account
}

# Data source to look up your existing DigitalOcean Cloud Firewall by its name
data "digitalocean_firewall" "existing_firewall" {
  name = var.cloud_firewall_name # This name must match your firewall in DO
}

# Define the DigitalOcean Droplet Resource
resource "digitalocean_droplet" "job_app_server" {
  name    = var.droplet_name
  region  = var.droplet_region
  size    = var.droplet_size
  image   = var.droplet_image

  # Associate the SSH key for initial root access
  ssh_keys = [data.digitalocean_ssh_key.initial_root_ssh_key.id]

  # Associate the existing Cloud Firewall
  firewall_id = data.digitalocean_firewall.existing_firewall.id

  monitoring = true
  # tags = ["web", "flask", "job-app"]

  # User data script to run on first boot
  user_data = <<-EOF
              #!/bin/bash
              # Exit on any error
              set -e

              # Variables passed from Terraform (or use direct values if preferred)
              APP_USER="${var.app_user_name}"
              DEPLOYMENT_PUBLIC_KEY="${var.deployment_ssh_public_key}"

              # Update and install packages
              export DEBIAN_FRONTEND=noninteractive
              apt-get update -y
              apt-get upgrade -y
              apt-get install -y nginx python3 python3-pip python3-venv libpq-dev build-essential # Removed ufw

              # Create the application user if it doesn't exist
              if ! id -u "$APP_USER" >/dev/null 2>&1; then
                  echo "Creating user $APP_USER"
                  useradd -m -s /bin/bash "$APP_USER"
                  echo "$APP_USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/$APP_USER" # Grant passwordless sudo
                  chmod 0440 "/etc/sudoers.d/$APP_USER"
              else
                  echo "User $APP_USER already exists"
              fi

              # Set up SSH for the application user
              APP_USER_HOME="/home/$APP_USER"
              SSH_DIR="$APP_USER_HOME/.ssh"
              AUTH_KEYS_FILE="$SSH_DIR/authorized_keys"

              echo "Setting up SSH for $APP_USER"
              mkdir -p "$SSH_DIR"
              chown "$APP_USER:$APP_USER" "$APP_USER_HOME" # Ensure home dir ownership
              chown "$APP_USER:$APP_USER" "$SSH_DIR"
              chmod 700 "$SSH_DIR"

              echo "$DEPLOYMENT_PUBLIC_KEY" > "$AUTH_KEYS_FILE" # Overwrite or create
              chown "$APP_USER:$APP_USER" "$AUTH_KEYS_FILE"
              chmod 600 "$AUTH_KEYS_FILE"
              echo "SSH authorized_keys configured for $APP_USER"

              # UFW configuration REMOVED as Cloud Firewall is used

              # Enable and start Nginx (systemd should handle this on install, but ensure)
              systemctl enable nginx
              systemctl start nginx
              echo "Nginx enabled and started"

              echo "User data script finished."
              EOF
}

# Output the Droplet's IP address
output "droplet_ip_address" {
  description = "The public IPv4 address of the new Droplet."
  value       = digitalocean_droplet.job_app_server.ipv4_address
}
