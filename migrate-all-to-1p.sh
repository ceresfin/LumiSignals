#!/usr/bin/env bash
# Migrate all LumiSignals secrets in config.yaml to 1Password (Lumi vault).
# Idempotent: re-running won't duplicate items or break the .tpl.
set -euo pipefail
cd ~/projects/LumiSignals

VAULT="Lumi"

echo "=== Ensure $VAULT vault exists ==="
if ! op vault list 2>/dev/null | awk 'NR>1 {print $2}' | grep -qx "$VAULT"; then
  op vault create "$VAULT"
  echo "✓ Created $VAULT vault"
else
  echo "✓ $VAULT vault exists"
fi

# Extract a field value from a specific section in config.yaml (silent).
extract() {
  local section="$1" field="$2"
  awk -v s="$section" -v f="$field" '
    $0 ~ "^"s":"           {in_section=1; next}
    /^[a-z]/               {in_section=0}
    in_section && $0 ~ "^  "f":" {
      sub("^  "f":[[:space:]]+", "")
      print
      exit
    }
  ' config.yaml
}

# Create or update a 1Password item with arbitrary fields (passed as key=value).
create_item_if_missing() {
  local title="$1"; shift
  if op item get "$title" --vault="$VAULT" >/dev/null 2>&1; then
    echo "  ✓ $title already exists, skipping"
  else
    op item create \
      --category="API Credential" \
      --title="$title" \
      --vault="$VAULT" \
      --tags=lumisignals \
      "$@" >/dev/null
    echo "  ✓ Created $title"
  fi
}

echo ""
echo "=== Migrating OANDA (already done — verifying) ==="
oanda_key=$(extract oanda api_key)
oanda_acct=$(extract oanda account_id)
oanda_env=$(extract oanda environment)
create_item_if_missing "LumiSignals - OANDA" \
  "username=$oanda_acct" "credential=$oanda_key" "environment=$oanda_env" \
  --url="https://api-fxpractice.oanda.com"

echo ""
echo "=== Migrating Signals API ==="
signals_key=$(extract signals api_key)
signals_url=$(extract signals api_url)
[ -z "$signals_key" ] && { echo "ERROR: signals.api_key not found"; exit 1; }
create_item_if_missing "LumiSignals - Signals API" \
  "credential=$signals_key" --url="$signals_url"

echo ""
echo "=== Migrating Massive ==="
massive_key=$(extract massive api_key)
[ -z "$massive_key" ] && { echo "ERROR: massive.api_key not found"; exit 1; }
create_item_if_missing "LumiSignals - Massive" "credential=$massive_key"

echo ""
echo "=== Migrating Schwab (OAuth credentials) ==="
schwab_id=$(extract schwab client_id)
schwab_secret=$(extract schwab client_secret)
schwab_redirect=$(extract schwab redirect_uri)
[ -z "$schwab_id" ] && { echo "ERROR: schwab.client_id not found"; exit 1; }
[ -z "$schwab_secret" ] && { echo "ERROR: schwab.client_secret not found"; exit 1; }
create_item_if_missing "LumiSignals - Schwab" \
  "username=$schwab_id" "credential=$schwab_secret" "redirect_uri=$schwab_redirect"

echo ""
echo "=== Rewrite config.yaml.tpl with all placeholders ==="
# Start fresh from the real config so we get all latest field values right
cp config.yaml config.yaml.tpl
python3 - <<PYEOF
replacements = [
    ("api_key: $oanda_key",       "api_key: {{ op://Lumi/LumiSignals - OANDA/credential }}"),
    ("account_id: $oanda_acct",   "account_id: {{ op://Lumi/LumiSignals - OANDA/username }}"),
    ("api_key: $signals_key",     "api_key: {{ op://Lumi/LumiSignals - Signals API/credential }}"),
    ("api_key: $massive_key",     "api_key: {{ op://Lumi/LumiSignals - Massive/credential }}"),
    ("client_id: $schwab_id",     "client_id: {{ op://Lumi/LumiSignals - Schwab/username }}"),
    ("client_secret: $schwab_secret", "client_secret: {{ op://Lumi/LumiSignals - Schwab/credential }}"),
]
with open("config.yaml.tpl") as f:
    c = f.read()
for old, new in replacements:
    if old not in c:
        print(f"  ⚠️  pattern not found in tpl: {old[:40]}...")
    c = c.replace(old, new, 1)
with open("config.yaml.tpl", "w") as f:
    f.write(c)
print("  ✓ All placeholders written")
PYEOF

echo ""
echo "=== Round-trip test: op inject .tpl → render → compare to original ==="
op inject -i config.yaml.tpl -o /tmp/rendered.yaml
if diff -q config.yaml /tmp/rendered.yaml >/dev/null 2>&1; then
  echo "✓ Rendered file matches original config.yaml exactly"
else
  echo "✗ MISMATCH — diff:"
  diff config.yaml /tmp/rendered.yaml | head -30
  exit 1
fi
rm -f /tmp/rendered.yaml

echo ""
echo "=========================================="
echo "All migrations complete. Items in 1Password Lumi vault:"
echo "  • LumiSignals - OANDA"
echo "  • LumiSignals - Signals API"
echo "  • LumiSignals - Massive"
echo "  • LumiSignals - Schwab"
echo ""
echo "Next: commit updated config.yaml.tpl, push, then update run.py to"
echo "regenerate config.yaml at startup:"
echo "  op inject -i config.yaml.tpl -o config.yaml && python run.py"
echo "=========================================="
