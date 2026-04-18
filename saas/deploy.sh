#!/bin/bash
# Deploy LumiSignals SaaS to Digital Ocean droplet
# Usage: bash deploy.sh

SERVER="root@174.138.46.187"
APP_DIR="/opt/lumisignals/app"

echo "Deploying LumiSignals SaaS..."

# Upload saas app files
rsync -avz --exclude '__pycache__' --exclude '*.pyc' \
  saas/ $SERVER:$APP_DIR/saas/

# Upload the core lumisignals package
rsync -avz --exclude '__pycache__' --exclude '*.pyc' --exclude 'web' \
  lumisignals/ $SERVER:$APP_DIR/lumisignals/

# Upload requirements
scp saas/requirements.txt $SERVER:$APP_DIR/

echo "Installing dependencies on server..."
ssh $SERVER "cd $APP_DIR && source /opt/lumisignals/venv/bin/activate && pip install -r requirements.txt"

# Only set up systemd service if it doesn't exist (preserves env vars)
ssh $SERVER 'if [ ! -f /etc/systemd/system/lumisignals.service ]; then
cat > /etc/systemd/system/lumisignals.service << EOF
[Unit]
Description=LumiSignals Bot SaaS
After=network.target postgresql.service redis.service

[Service]
Type=exec
User=root
WorkingDirectory=/opt/lumisignals/app
Environment=PYTHONPATH=/opt/lumisignals/app
ExecStart=/opt/lumisignals/venv/bin/gunicorn -w 4 -b 127.0.0.1:8000 saas.app:create_app()
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
echo "Systemd service created"
else
echo "Systemd service already exists — skipping (preserving env vars)"
fi'

ssh $SERVER "systemctl daemon-reload && systemctl enable lumisignals && systemctl restart lumisignals"

# Only set up Nginx if config doesn't already exist (preserves SSL config from certbot)
ssh $SERVER 'if [ ! -f /etc/nginx/sites-available/lumisignals ]; then
cat > /etc/nginx/sites-available/lumisignals << EOF
server {
    listen 80;
    server_name bot.lumitrade.ai;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
ln -sf /etc/nginx/sites-available/lumisignals /etc/nginx/sites-enabled/
echo "Nginx config created"
else
echo "Nginx config already exists — skipping (preserving SSL)"
fi'

ssh $SERVER "nginx -t && systemctl reload nginx"

echo ""
echo "Done! Visit http://bot.lumitrade.ai (or http://174.138.46.187)"
echo "Run 'ssh $SERVER certbot --nginx -d bot.lumitrade.ai' for HTTPS"
