#!/bin/bash

# Logs directory
mkdir -p logs

CONFIG_FILE="${ODOO_CONFIG:-odoo.conf}"

resolve_db_name() {
    if [ -n "${ODOO_DB:-}" ]; then
        printf '%s\n' "$ODOO_DB"
        return
    fi

    if [ -f "$CONFIG_FILE" ]; then
        local config_db
        config_db=$(python3 - <<'PY'
import configparser
import os

cfg = configparser.ConfigParser()
path = os.environ.get("CONFIG_FILE", "odoo.conf")
cfg.read(path)
value = ""
if cfg.has_section("options"):
    value = str(cfg["options"].get("db_name", "")).strip()
if value.lower() in {"", "false", "none"}:
    value = ""
print(value)
PY
)
        if [ -n "$config_db" ]; then
            printf '%s\n' "$config_db"
            return
        fi
    fi

    printf 'default\n'
}

DB_NAME="$(resolve_db_name)"
export ODOO_DB="$DB_NAME"
export CONFIG_FILE

echo "Starting Odoo Server in background..."
# Start Odoo in the background, redirecting output to logs/odoo.log
# Using -c odoo.conf as standard for your server
python3 src/odoo-bin -c "$CONFIG_FILE" -d "$DB_NAME" "$@" > logs/odoo.log 2>&1 &
ODOO_PID=$!
echo $ODOO_PID > .odoo.pid

echo "Waiting Odoo to initialize (10s)..."
sleep 10

echo "Starting Telegram Bot in background..."
# Start the Telegram Bot in the background, redirecting output to logs/bot.log
python3 custom_addons/van_sales_pharma/telegram_bot.py > logs/bot.log 2>&1 &
BOT_PID=$!
echo $BOT_PID > .bot.pid

echo "------------------------------------------------"
echo "✅ Both processes are now running in the BACKGROUND."
echo "Odoo PID: $ODOO_PID"
echo "Bot PID: $BOT_PID"
echo "------------------------------------------------"
echo "To see Odoo logs: tail -f logs/odoo.log"
echo "To see Bot logs:  tail -f logs/bot.log"
echo "To stop them: kill $ODOO_PID $BOT_PID"
