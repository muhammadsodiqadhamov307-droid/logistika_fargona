import os
import sys
import logging
import configparser
import xmlrpc.client
import time
import getpass
import subprocess
from datetime import datetime

try:
    import psycopg2
except Exception:  # pragma: no cover - optional runtime fallback
    psycopg2 = None

from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)

# Set up raw logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# We use localhost here just to connect to the local database via XML-RPC.
# The actual public URL that gets sent to Telegram (for Web Apps) is pulled dynamically
# from Odoo's System Settings (web.base.url or van_telegram_odoo_url) in get_web_app_button.
ODOO_URL = "http://localhost:8069"
DEFAULT_ODOO_DB = "default"
ODOO_USER = "admin"  # Hardcoded per instructions for local script
ODOO_PASSWORD = os.environ.get('ODOO_PASSWORD', 'admin') # Read from env, fallback to admin
ODOO_CONFIG = os.environ.get('ODOO_CONFIG', 'odoo.conf')

# State definitions for Registration Conversation
ASK_NAME, ASK_PHONE = range(2)

def get_odoo_models():
    """Authenticates and returns the xmlrpc models proxy, plus the uid"""
    try:
        odoo_db = get_odoo_db()
        common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common')
        uid = common.authenticate(odoo_db, ODOO_USER, ODOO_PASSWORD, {})
        if not uid:
            logger.error(f"Authentication to Odoo failed for database: {odoo_db}")
            return None, None
        models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object')
        return models, uid
    except Exception as e:
        logger.error(f"Odoo XML-RPC Error: {e}")
        return None, None

def get_odoo_config():
    parser = configparser.ConfigParser()
    if parser.read(ODOO_CONFIG):
        return parser['options'] if parser.has_section('options') else {}
    return {}

def _normalize_config_value(value, default=''):
    if value is None:
        return default
    value = str(value).strip()
    if value.lower() in {'', 'false', 'none'}:
        return default
    return value

def get_odoo_db():
    """Resolve the database from env/config, or auto-pick a single live DB."""
    env_db = _normalize_config_value(os.environ.get('ODOO_DB'), '')
    if env_db:
        return env_db

    config = get_odoo_config()
    config_db = _normalize_config_value(config.get('db_name'), '')
    if config_db:
        return config_db

    conn = get_db_connection()
    if conn:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT datname
                        FROM pg_database
                        WHERE datistemplate = false
                          AND datallowconn = true
                          AND datname NOT IN ('postgres')
                        ORDER BY datname
                        """
                    )
                    db_names = [row[0] for row in cur.fetchall() if row and row[0]]
                    if len(db_names) == 1:
                        return db_names[0]
        except Exception as e:
            logger.warning(f"Automatic DB discovery failed: {e}")
        finally:
            conn.close()

    return DEFAULT_ODOO_DB

def read_config_file_value(*keys, default=''):
    """Read one of the given keys directly from odoo.conf [options]."""
    config = get_odoo_config()
    for key in keys:
        value = _normalize_config_value(config.get(key), '')
        if value:
            return value
    return default

def get_db_connection():
    """Connect directly to local PostgreSQL using odoo.conf values."""
    if psycopg2 is None:
        return None

    config = get_odoo_config()
    dbname = get_odoo_db()
    dbuser = _normalize_config_value(config.get('db_user'), getpass.getuser())
    dbpassword = _normalize_config_value(config.get('db_password'), '')
    dbhost = _normalize_config_value(config.get('db_host'), '')
    dbport = _normalize_config_value(config.get('db_port'), '')

    connect_kwargs = {
        'dbname': dbname,
        'user': dbuser,
    }
    if dbpassword:
        connect_kwargs['password'] = dbpassword
    if dbhost:
        connect_kwargs['host'] = dbhost
    if dbport:
        try:
            connect_kwargs['port'] = int(dbport)
        except ValueError:
            logger.warning(f"Ignoring invalid db_port from config: {dbport}")

    try:
        return psycopg2.connect(**connect_kwargs)
    except Exception as e:
        logger.warning(f"Direct PostgreSQL connection failed: {e}")
        return None

def read_config_param_db(key):
    """Read ir_config_parameter directly from PostgreSQL."""
    conn = get_db_connection()
    if not conn:
        return ''
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM ir_config_parameter WHERE key = %s LIMIT 1", (key,))
                row = cur.fetchone()
                return row[0] if row and row[0] else ''
    except Exception as e:
        logger.warning(f"Direct DB read failed for config param {key}: {e}")
        return ''
    finally:
        conn.close()

def read_config_param_psql(key):
    """Fallback to local psql command when psycopg2 is unavailable or unsuitable."""
    config = get_odoo_config()
    dbname = get_odoo_db()
    dbuser = _normalize_config_value(config.get('db_user'), getpass.getuser())
    dbhost = _normalize_config_value(config.get('db_host'), '')
    dbport = _normalize_config_value(config.get('db_port'), '')

    cmd = ['psql', '-At', '-d', dbname, '-U', dbuser, '-c', f"SELECT value FROM ir_config_parameter WHERE key = '{key}' LIMIT 1;"]
    if dbhost:
        cmd.extend(['-h', dbhost])
    if dbport:
        cmd.extend(['-p', dbport])

    env = os.environ.copy()
    dbpassword = _normalize_config_value(config.get('db_password'), '')
    if dbpassword:
        env['PGPASSWORD'] = dbpassword

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
        if result.returncode == 0:
            return (result.stdout or '').strip()
        logger.warning(f"psql fallback failed for config param {key}: {result.stderr.strip()}")
    except Exception as e:
        logger.warning(f"psql execution failed for config param {key}: {e}")
    return ''

def read_config_param(models, uid, key):
    """Read ir.config_parameter robustly across versions."""
    odoo_db = get_odoo_db()
    try:
        records = models.execute_kw(
            odoo_db, uid, ODOO_PASSWORD,
            'ir.config_parameter', 'search_read',
            [[('key', '=', key)]],
            {'fields': ['value'], 'limit': 1}
        )
        if records:
            return records[0].get('value') or ''
    except Exception as e:
        logger.warning(f"search_read failed for config param {key}: {e}")

    try:
        record_ids = models.execute_kw(
            odoo_db, uid, ODOO_PASSWORD,
            'ir.config_parameter', 'search',
            [[('key', '=', key)]],
            {'limit': 1}
        )
        if record_ids:
            records = models.execute_kw(
                odoo_db, uid, ODOO_PASSWORD,
                'ir.config_parameter', 'read',
                [record_ids, ['value']]
            )
            if records:
                return records[0].get('value') or ''
    except Exception as e:
        logger.warning(f"search/read failed for config param {key}: {e}")

    return ''

def get_bot_token():
    """Fetch the Telegram bot token with env/config/database fallbacks."""
    env_token = (
        os.environ.get('VAN_TELEGRAM_BOT_TOKEN')
        or os.environ.get('TELEGRAM_BOT_TOKEN')
    )
    if env_token:
        return env_token.strip()

    config_token = read_config_file_value('van_telegram_bot_token', 'telegram_bot_token')
    if config_token:
        return config_token.strip()

    db_token = read_config_param_db('van.telegram.bot.token')
    if db_token:
        return db_token.strip()

    psql_token = read_config_param_psql('van.telegram.bot.token')
    if psql_token:
        return psql_token.strip()

    for attempt in range(1, 6):
        config_token = read_config_file_value('van_telegram_bot_token', 'telegram_bot_token')
        if config_token:
            return config_token.strip()
        db_token = read_config_param_db('van.telegram.bot.token')
        if db_token:
            return db_token.strip()
        psql_token = read_config_param_psql('van.telegram.bot.token')
        if psql_token:
            return psql_token.strip()
        models, uid = get_odoo_models()
        if models:
            token = read_config_param(models, uid, 'van.telegram.bot.token')
            if token:
                return token.strip()
            logger.warning(f"Telegram bot token not found on attempt {attempt}/5")
        else:
            logger.warning(f"Could not connect to Odoo on attempt {attempt}/5")
        time.sleep(3)
    return None

def get_web_app_button(chat_id):
    """Returns an InlineKeyboardButton for the Telegram Web App, fully resolving the URL"""
    base_url = read_config_param_db('van.telegram.odoo.url')
    if not base_url:
        base_url = read_config_param_db('van_telegram_odoo_url')
    if not base_url:
        base_url = read_config_param_db('web.base.url')
    if not base_url:
        base_url = read_config_param_psql('van.telegram.odoo.url')
    if not base_url:
        base_url = read_config_param_psql('van_telegram_odoo_url')
    if not base_url:
        base_url = read_config_param_psql('web.base.url')

    models, uid = get_odoo_models()
    if not base_url and models:
        base_url = read_config_param(models, uid, 'van.telegram.odoo.url')
        if not base_url:
            base_url = read_config_param(models, uid, 'van_telegram_odoo_url')
        if not base_url:
            base_url = read_config_param(models, uid, 'web.base.url')
    if not base_url:
        return None
        
    if not base_url.startswith('http'):
        base_url = "https://" + base_url.lstrip('/')
    elif base_url.startswith('http://') and not ('localhost' in base_url or '127.0.0.1' in base_url):
        base_url = base_url.replace('http://', 'https://')
        
    base_url = base_url.rstrip('/')
    web_app_url = f"{base_url}/van/client/request?chat_id={chat_id}&v={int(time.time())}"
    
    return InlineKeyboardButton(text="🛒 Zakaz berish", web_app={"url": web_app_url})

def partner_field_exists(models, uid, field_name):
    """Check whether a field exists on res.partner in the live Odoo registry."""
    try:
        fields_info = models.execute_kw(
            get_odoo_db(), uid, ODOO_PASSWORD,
            'res.partner', 'fields_get',
            [[field_name]],
            {'attributes': ['string', 'type']}
        )
        return field_name in (fields_info or {})
    except Exception as e:
        logger.warning(f"Unable to inspect res.partner field {field_name}: {e}")
        return False

def build_main_menu(chat_id=None):
    keyboard = [
        [InlineKeyboardButton("💰 Balans (Qarz)", callback_data='menu_balans')],
        [InlineKeyboardButton("📋 Barcha tranzaksiyalar", callback_data='menu_tranzaksiyalar')],
        [InlineKeyboardButton("🧾 Savdo cheklari (Batafsil)", callback_data='menu_savdo_cheklari')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- START / MENU ---

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = str(update.effective_chat.id)
    models, uid = get_odoo_models()
    odoo_db = get_odoo_db()
    if not models:
        await update.message.reply_text("Tizim bilan bog'lanishda xatolik yuz berdi. Iltimos keyinroq urinib ko'ring.")
        return ConversationHandler.END

    if not partner_field_exists(models, uid, 'telegram_chat_id'):
        logger.error(
            "res.partner.telegram_chat_id is missing in database %s. "
            "Bot will return chat id only until van_sales_pharma is upgraded on the live DB.",
            odoo_db,
        )
        await update.message.reply_text(
            f"Sizning Telegram Chat ID raqamingiz:\n\n<code>{chat_id}</code>",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    # Check if client already exists by telegram_chat_id
    partner_ids = models.execute_kw(odoo_db, uid, ODOO_PASSWORD, 'res.partner', 'search', [[('telegram_chat_id', '=', chat_id)]])
    
    if partner_ids:
        # Already registered
        await update.message.reply_text(
            "Assalomu alaykum! Siz allaqachon ro'yxatdan o'tgansiz.\nQuyidagi menyudan foydalanishingiz mumkin:",
            reply_markup=build_main_menu(chat_id)
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"Sizning Telegram Chat ID raqamingiz:\n\n<code>{chat_id}</code>\n\n"
        "Uni tizimga biriktirish uchun shu raqamni operatorga yoki agentga yuboring.",
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['partner_name'] = update.message.text
    
    # Request Phone number via Reply Keyboard for convenience
    contact_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Raqamni yuborish", request_contact=True)]], 
        resize_keyboard=True, 
        one_time_keyboard=True
    )
    
    await update.message.reply_text(
        "Rahmat! Endi telefon raqamingizni yuboring (yoki pastdagi tugmani bosing):",
        reply_markup=contact_keyboard
    )
    return ASK_PHONE

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Process either text input or contact card
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text
        
    chat_id = str(update.effective_chat.id)
    name = context.user_data.get('partner_name', 'Noma\'lum')
    
    models, uid = get_odoo_models()
    odoo_db = get_odoo_db()
    if not models:
        await update.message.reply_text("Tizim xatoligi.")
        return ConversationHandler.END

    if not partner_field_exists(models, uid, 'telegram_chat_id'):
        await update.message.reply_text(
            "Tizimda telegram maydoni hali tayyor emas. Iltimos admin bilan tekshirib ko'ring."
        )
        return ConversationHandler.END

    # 1. Search existing partner by phone to link instead of duplicate
    if phone.startswith('+'):
        search_phone = phone
    else:
        search_phone = '+' + phone.lstrip('0')
        
    # Simple search (can be enhanced for format variations)
    existing_ids = models.execute_kw(odoo_db, uid, ODOO_PASSWORD, 'res.partner', 'search', [[('phone', 'ilike', phone[-9:])]])
    
    if existing_ids:
        # Link to existing
        models.execute_kw(odoo_db, uid, ODOO_PASSWORD, 'res.partner', 'write', [existing_ids[0], {
            'telegram_chat_id': chat_id
        }])
    else:
        # Create new
        models.execute_kw(odoo_db, uid, ODOO_PASSWORD, 'res.partner', 'create', [{
            'name': name,
            'phone': phone,
            'telegram_chat_id': chat_id,
            'x_is_van_customer': True
        }])

    # Remove the bulky reply keyboard
    from telegram import ReplyKeyboardRemove
    await update.message.reply_text(
        "✅ Ro'yxatdan o'tdingiz!\nEndi botdan foydalanishingiz mumkin.",
        reply_markup=ReplyKeyboardRemove()
    )
    
    await update.message.reply_text(
        "Asosiy Menu:",
        reply_markup=build_main_menu(chat_id)
    )
    return ConversationHandler.END

async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Ro'yxatdan o'tish bekor qilindi. /start ni bosib qaytadan boshlashingiz mumkin.")
    return ConversationHandler.END


# --- MENU CALLBACKS ---

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Acknowledge the button press
    
    chat_id = str(update.effective_chat.id)
    data = query.data
    
    models, uid = get_odoo_models()
    odoo_db = get_odoo_db()
    if not models:
        await query.edit_message_text("Ma'lumotlarni olishda xatolik yuz berdi.")
        return

    if not partner_field_exists(models, uid, 'telegram_chat_id'):
        await query.edit_message_text(
            "Telegram maydoni bu bazada hali tayyor emas. Iltimos admin bilan tekshirib ko'ring."
        )
        return

    # Find the partner
    partner_ids = models.execute_kw(odoo_db, uid, ODOO_PASSWORD, 'res.partner', 'search', [[('telegram_chat_id', '=', chat_id)]])
    if not partner_ids:
        await query.edit_message_text("Sizning hisobingiz topilmadi. Iltimos /start ni bosing.")
        return
        
    partner_id = partner_ids[0]

    if data == 'menu_balans':
        # Refresh the compute field before reading
        models.execute_kw(odoo_db, uid, ODOO_PASSWORD, 'res.partner', 'get_partner_van_debt', [partner_id])
        partner_data = models.execute_kw(odoo_db, uid, ODOO_PASSWORD, 'res.partner', 'read', [[partner_id], ['x_van_total_due']])
        if partner_data:
            debt = partner_data[0].get('x_van_total_due', 0.0)
            await query.edit_message_text(
                f"💰 <b>Sizning joriy qarzingiz (Balans):</b>\n\n💵 {debt:,.0f} so'm",
                parse_mode='HTML',
                reply_markup=build_main_menu()
            )
            
    elif data == 'menu_tranzaksiyalar':
        # Fetch van.dashboard.detail for this partner
        records = models.execute_kw(odoo_db, uid, ODOO_PASSWORD, 'van.dashboard.detail', 'search_read', [
            [('partner_id', '=', partner_id)]
        ], {'fields': ['date', 'transaction_type', 'amount'], 'order': 'date desc', 'limit': 15})
        
        if not records:
             await query.edit_message_text("Tranzaksiyalar tarixi bo'sh.", reply_markup=build_main_menu(chat_id))
             return
             
        msg = "📋 <b>So'nggi 15 ta tranzaksiya:</b>\n\n"
        for r in records:
            dt = r['date'] # "2026-03-01 14:30:00"
            ttype = r['transaction_type']
            icon = "✅ Kirim" if ttype == "kirim" else ("🛍 Savdo" if ttype == "sale" else "➖ Chiqim")
            msg += f"📅 {dt[:16]}\n  {icon} | {r['amount']:,.0f} so'm\n\n"
            
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=build_main_menu(chat_id))

    elif data == 'menu_savdo_cheklari':
        # Fetch last 5 van.pos.order list
        orders = models.execute_kw(odoo_db, uid, ODOO_PASSWORD, 'van.pos.order', 'search_read', [
            [('partner_id', '=', partner_id), ('state', '=', 'done')]
        ], {'fields': ['name', 'date', 'amount_total', 'line_ids'], 'order': 'date desc', 'limit': 5})
        
        if not orders:
             await query.edit_message_text("Savdo cheklari tarixi bo'sh.", reply_markup=build_main_menu(chat_id))
             return
             
        msg = "🧾 <b>So'nggi 5 ta savdo cheki (Batafsil):</b>\n\n"
        for o in orders:
            dt = o['date'][:16]
            msg += f"📄 <b>{o['name']}</b> | 📅 {dt}\n"
            
            # Fetch lines for this order
            lines = models.execute_kw(odoo_db, uid, ODOO_PASSWORD, 'van.pos.order.line', 'read', [
                o['line_ids'], ['product_id', 'qty', 'price_unit', 'subtotal']
            ])
            
            for l in lines:
                p_name = l['product_id'][1]
                msg += f" ▪️ {p_name}\n    {int(l['qty'])} x {l['price_unit']:,.0f} = {l['subtotal']:,.0f} so'm\n"
            
            msg += f"💰 <b>Jami: {o['amount_total']:,.0f} so'm</b>\n"
            msg += "---------------------------------\n\n"
            
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=build_main_menu(chat_id))


async def generic_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fallback handler for text if they type something randomly"""
    await update.message.reply_text("Menyulardan foydalanish uchun /start yoki /menu buyrug'ini tering.")

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fallback command to reshow the main menu without registering"""
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text("Asosiy Menu:", reply_markup=build_main_menu(chat_id))

def main():
    token = get_bot_token()
    if not token:
        logger.error("No Telegram Bot Token found in Odoo 'van.telegram.bot.token' sys parameter.")
        logger.error("Please add the token in the Odoo Interface before running this script.")
        # If testing without an interface, you can override token literally here
        # token = "YOUR_BOT_TOKEN_HERE"
        sys.exit(1)

    logger.info("Initializing Telegram Bot...")
    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler('start', start_cmd))

    # Hard Menu command
    application.add_handler(CommandHandler('menu', menu_cmd))

    # Inline Button callbacks
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Generic text fallback string
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, generic_text_handler))

    # Run the bot forever!
    logger.info("Bot is polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
