#!/usr/bin/env bash
set -euo pipefail
cd ~/projects/LumiSignals

echo "=== Step 1: ensure Lumi vault exists ==="
if ! op vault list 2>/dev/null | awk 'NR>1 {print $2}' | grep -qx "Lumi"; then
  op vault create Lumi
  echo "✓ Created Lumi vault"
else
  echo "✓ Lumi vault already exists"
fi

extract_oanda() {
  awk -v f="$1" '
    /^oanda:/     {in_section=1; next}
    /^[a-z]/      {in_section=0}
    in_section && $0 ~ "^  "f":" {
      sub("^  "f":[[:space:]]+", "")
      print
      exit
    }
  ' config.yaml
}

echo ""
echo "=== Step 2: extract OANDA fields ==="
api_key=$(extract_oanda api_key)
account_id=$(extract_oanda account_id)
environment=$(extract_oanda environment)
[ -z "$api_key" ] && { echo "ERROR: api_key not found"; exit 1; }
[ -z "$account_id" ] && { echo "ERROR: account_id not found"; exit 1; }
echo "✓ api_key (${#api_key} chars), account_id (${#account_id} chars), environment"

echo ""
echo "=== Step 3: create 1Password item ==="
if op item get "LumiSignals - OANDA" --vault=Lumi >/dev/null 2>&1; then
  echo "✓ Item exists, skipping"
else
  op item create \
    --category="API Credential" \
    --title="LumiSignals - OANDA" \
    --vault=Lumi \
    --tags=lumisignals,oanda \
    "username=$account_id" \
    "credential=$api_key" \
    "environment=$environment" \
    --url="https://api-fxpractice.oanda.com" >/dev/null
  echo "✓ Created LumiSignals - OANDA"
fi

echo ""
echo "=== Step 4: write config.yaml.tpl with op:// placeholders ==="
cp config.yaml config.yaml.tpl
# Unique values → safe to replace globally with sed (each value occurs once)
python3 -c "
import sys
with open('config.yaml.tpl', 'r') as f:
    content = f.read()
content = content.replace('api_key: ${api_key}', 'api_key: {{ op://Lumi/LumiSignals - OANDA/credential }}', 1)
content = content.replace('account_id: ${account_id}', 'account_id: {{ op://Lumi/LumiSignals - OANDA/username }}', 1)
with open('config.yaml.tpl', 'w') as f:
    f.write(content)
"
echo "✓ config.yaml.tpl written"

echo ""
echo "=== Step 5: test round-trip via op inject ==="
op inject -i config.yaml.tpl -o /tmp/config-render-test.yaml
if diff -q config.yaml /tmp/config-render-test.yaml >/dev/null 2>&1; then
  echo "✓ Render matches original config.yaml"
else
  echo "✗ MISMATCH:"
  diff config.yaml /tmp/config-render-test.yaml | head -15
fi
rm -f /tmp/config-render-test.yaml

echo ""
echo "==========================================="
echo "OANDA migration complete."
echo ""
echo "  config.yaml.tpl  → safe to commit"
echo "  config.yaml       → stays gitignored"
echo "  regenerate any time: op inject -i config.yaml.tpl -o config.yaml"
echo ""
echo "  2 more api_keys (lines 9, 38) in config.yaml for other services"
echo "  → migrate those next, similar pattern."
echo "==========================================="
