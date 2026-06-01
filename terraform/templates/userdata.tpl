#!/bin/bash
exec > /var/log/nat-setup.log 2>&1
set -x

echo "=== NAT Setup Started at $(date) ==="
echo "Private subnet CIDR: ${private_subnet_cidr}"
echo "Private subnet 2 CIDR: ${private_subnet_2_cidr}"

# Install and configure CloudWatch Agent
dnf install -y amazon-cloudwatch-agent

cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << CWEOF
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/nat-setup.log",
            "log_group_name": "${log_group_name}",
            "log_stream_name": "{instance_id}/nat-setup"
          },
          {
            "file_path": "/var/log/messages",
            "log_group_name": "${log_group_name}",
            "log_stream_name": "{instance_id}/messages"
          }
        ]
      }
    }
  }
}
CWEOF

/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -s \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json

# Enable IP forwarding immediately
echo 1 > /proc/sys/net/ipv4/ip_forward
echo 0 > /proc/sys/net/ipv4/conf/all.send_redirects

# Make IP forwarding persistent
cat <<EOF > /etc/sysctl.d/99-nat.conf
net.ipv4.ip_forward = 1
net.ipv4.conf.all.send_redirects = 0
EOF

sysctl -p /etc/sysctl.d/99-nat.conf

# Find the primary network interface
PRIMARY_IF=$(ip route | grep default | awk '{print $5}' | head -1)
echo "Primary interface: $PRIMARY_IF"

# Install iptables
dnf install -y iptables

# Configure NAT with iptables
# MASQUERADE: Rewrite source IP of outbound packets from private subnets
iptables -t nat -A POSTROUTING -s ${private_subnet_cidr} -o $PRIMARY_IF -j MASQUERADE
iptables -t nat -A POSTROUTING -s ${private_subnet_2_cidr} -o $PRIMARY_IF -j MASQUERADE

# FORWARD: Allow traffic forwarding
iptables -P FORWARD ACCEPT
iptables -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -A FORWARD -s ${private_subnet_cidr} -j ACCEPT
iptables -A FORWARD -s ${private_subnet_2_cidr} -j ACCEPT

# Save rules for persistence
mkdir -p /etc/iptables
iptables-save > /etc/iptables/rules.v4

# Create systemd service to restore rules on boot
cat <<'EOF' > /etc/systemd/system/iptables-restore.service
[Unit]
Description=Restore iptables rules
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/iptables-restore /etc/iptables/rules.v4
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable iptables-restore.service

# Verify configuration
echo "=== Verification ==="
echo "IP forwarding: $(cat /proc/sys/net/ipv4/ip_forward)"
echo ""
echo "NAT rules:"
iptables -t nat -L -n -v
echo ""
echo "FORWARD rules:"
iptables -L FORWARD -n -v

echo "=== NAT Setup Completed at $(date) ==="