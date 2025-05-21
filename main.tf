# main.tf

# Data source to look up your existing SSH key by its name for root access
data "digitalocean_ssh_key" "initial_root_ssh_key" {
  name = var.ssh_key_name_for_root # This name must match an SSH key name in your DO account
}

# Data source for existing_firewall REMOVED

# Define the DigitalOcean Droplet Resource
resource "digitalocean_droplet" "job_app_server" {
  name    = var.droplet_name
  region  = var.droplet_region
  size    = var.droplet_size
  image   = var.droplet_image

  # Associate the SSH key for initial root access
  ssh_keys = [data.digitalocean_ssh_key.initial_root_ssh_key.id]

  monitoring = true
  # firewall_ids argument removed as firewall association is now handled by the
  # digitalocean_firewall resource's droplet_ids attribute.

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

# Define/Manage the DigitalOcean Cloud Firewall
resource "digitalocean_firewall" "updated_firewall" {
  # Use the name directly from the variable.
  # If a firewall with this name already exists on DigitalOcean and is not
  # managed by this Terraform resource, 'terraform apply' will error.
  # In that case, you would need to import it first:
  # terraform import digitalocean_firewall.updated_firewall <EXISTING_FIREWALL_ID>
  name        = var.cloud_firewall_name

  # Assigns this firewall to the Droplet created above
  droplet_ids = [digitalocean_droplet.job_app_server.id]

  # Define your desired inbound rules
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22" # SSH
    source_addresses = ["0.0.0.0/0", "::/0"] # Allow from anywhere
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "80" # HTTP
    source_addresses = ["0.0.0.0/0", "::/0"] # Allow from anywhere
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "443" # HTTPS
    source_addresses = ["0.0.0.0/0", "::/0"] # Allow from anywhere
  }

  # Define your desired outbound rules (allowing all TCP is common)
  outbound_rule {
    protocol              = "tcp"
    port_range            = "all" # Or "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
  outbound_rule {
    protocol              = "udp"
    port_range            = "all" # Or "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}

# Output the Droplet's IP address
output "droplet_ip_address" {
  description = "The public IPv4 address of the new Droplet."
  value       = digitalocean_droplet.job_app_server.ipv4_address
}
