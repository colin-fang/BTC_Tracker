import logging
import asyncio

import aiohttp
import re

from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_storage import StatePickleStorage
from telebot import asyncio_filters
import telebot.types

import json
import time
import os
from datetime import datetime
#dummy
wallets_file = "wallet_settings.json"

with open("token.txt", "r") as token:
    TOKEN = token.read()

logging.basicConfig(filename="logs.log", level=logging.ERROR)
logger = logging.getLogger("TeleBot")

bot = AsyncTeleBot(TOKEN, state_storage=StatePickleStorage("Storage/storage.pkl"))
bot.add_custom_filter(asyncio_filters.StateFilter(bot))
bot.add_custom_filter(asyncio_filters.TextStartsFilter())

icons = {
    "wallet": "💼",
    "cancel": "🔙",
    "start_tracking": "🔔",
    "stop_tracking": "🔕",
    "settings": "🔧",
}
btns = {
    "wallet": telebot.types.KeyboardButton("{wallet} BTC Wallet".format(**icons)),
    "cancel": telebot.types.KeyboardButton("{cancel} Cancel".format(**icons)),
    "start_tracking": telebot.types.KeyboardButton("{start_tracking} Transaction tracking on".format(**icons)),
    "stop_tracking": telebot.types.KeyboardButton("{stop_tracking} Transaction tracking off".format(**icons)),
    "settings": telebot.types.KeyboardButton("{settings} Settings".format(**icons)),
    "set_wallet": telebot.types.InlineKeyboardButton("Set new wallet", callback_data="set_new_wallet"),
    "check_balance": telebot.types.InlineKeyboardButton("Check balance", callback_data="check_balance"),
}
keyboards = {
    "menu": telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1).add(btns["wallet"], btns["start_tracking"]),
    "tracking": telebot.types.ReplyKeyboardMarkup(resize_keyboard=True).add(btns["stop_tracking"]),
    "query": telebot.types.ReplyKeyboardMarkup(resize_keyboard=True).add(btns["cancel"]),
    "wallet": telebot.types.InlineKeyboardMarkup(row_width=1).add(btns["set_wallet"], btns["check_balance"]),
    "set_wallet": telebot.types.InlineKeyboardMarkup(row_width=1).add(btns["set_wallet"]),
}


class HTTPSession:
    session = None

    @classmethod
    async def get_session(cls):
        cls.session = aiohttp.ClientSession(connector=aiohttp.TCPConnector())

    @classmethod
    async def get_json_response(cls, url):
        if cls.session is None or cls.session.closed:
            cls.session = aiohttp.ClientSession(connector=aiohttp.TCPConnector())
        async with cls.session.request('get', url) as response:
            if response.status == 200:
                return await response.json()
            logger.error(f"Could not reach {url}. Error code {response.status}")
        return None


# Load wallet settings from file
def load_wallet_settings():
    """Loads wallet settings from a JSON file, or initializes an empty dictionary if the file is missing."""
    if os.path.exists(wallets_file):
        try:
            with open(wallets_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    return {}

# Save wallet settings to file
def save_wallet_settings():
    """Saves the updated wallet settings back to the JSON file."""
    with open(wallets_file, "w") as f:
        json.dump(wallet_settings, f, indent=4)

# Load wallets on startup
wallet_settings = load_wallet_settings()

def is_tracking_active(wallet):
    """Check if today's date is within the tracking start and end date from the JSON file."""
    today = datetime.now().strftime("%Y-%m-%d")  # Get current date as YYYY-MM-DD
    
    # If wallet is not found, assume it shouldn't be tracked
    if wallet not in wallet_settings:
        return False

    start_date = wallet_settings[wallet].get("start_date", "2000-01-01")  # Default: track from long ago
    end_date = wallet_settings[wallet].get("end_date", "2100-01-01")  # Default: track forever

    return start_date <= today <= end_date  # Returns True if within range

async def return_to_menu(chat_id, user_id, message):
    """ Sends a message and resets user's state back to 'menu' """
    await bot.send_message(chat_id, text=message, reply_markup=keyboards["menu"])
    await bot.set_state(user_id, "menu")


async def start_tracking(chat_id, user_id, wallet):
    """Confirms the API is reachable, then hands off monitoring to poke_blockchain."""
    await bot.send_message(chat_id, text="Starting transaction monitoring...", reply_markup=keyboards["tracking"])

    # Test connection to mempool.space API before tracking starts
    wallet_info = await HTTPSession.get_json_response(f"https://mempool.space/api/address/{wallet}")

    if not wallet_info:
        await bot.send_message(chat_id, "⚠️ Could not reach mempool.space API. Please try again later.")
        return

    print(f"✅ Connection to mempool.space successful. Monitoring wallet: {wallet}")
    await bot.send_message(chat_id, "✅ Connection to mempool.space successful. Starting monitoring...")

    # Start continuous tracking in poke_blockchain
    await poke_blockchain(chat_id, user_id)

async def return_balance(wallet):
    # Load wallet from JSON file instead of temporary storage
    wallet_settings = load_wallet_settings()
    
    if wallet is None:
        await bot.send_message(call.message.chat.id, "No wallet found in records. Please add one.")
        return

    # Fetch wallet info from Mempool API
    wallet_info = await HTTPSession.get_json_response(f"https://mempool.space/api/address/{wallet}")

    if not wallet_info:
        await bot.send_message(call.message.chat.id, "⚠️ Could not fetch wallet info from mempool.space.")
        return

    # Extract balance details
    funded_txo_sum = wallet_info["chain_stats"].get("funded_txo_sum", 0)
    spent_txo_sum = wallet_info["chain_stats"].get("spent_txo_sum", 0)
    mempool_funded = wallet_info["mempool_stats"].get("funded_txo_sum", 0)  # Unconfirmed incoming
    mempool_spent = wallet_info["mempool_stats"].get("spent_txo_sum", 0)  # Unconfirmed outgoing
    tx_count = wallet_info["chain_stats"].get("tx_count", 0)

    # Correct balance calculation (confirmed + mempool)
    confirmed_balance = (funded_txo_sum - spent_txo_sum) / 100_000_000  # BTC
    mempool_balance = (mempool_funded - mempool_spent) / 100_000_000  # BTC
    total_balance = confirmed_balance + mempool_balance  # Include unconfirmed tx

    return total_balance

async def poke_blockchain(chat_id, user_id):
    """Continuously checks for new transactions and alerts only when a new one is found for all wallets."""
    seen_transactions = {}  # Dictionary to track seen transactions per wallet
    iteration = 0

    while await bot.get_state(user_id) == "tracking":
        iteration += 1

        # Load latest wallet settings each cycle (in case new wallets are added)
        wallet_settings = load_wallet_settings()

        if not wallet_settings:
            print(f"❌ No wallets found. Stopping tracking.")
            await bot.set_state(user_id, "menu")
            await bot.send_message(chat_id, text="❌ No wallets found. Stopping tracking.", reply_markup=keyboards["menu"])
            return

        response = f"🔎 **Checking transaction status (Cycle {iteration})**\n"

        for wallet in wallet_settings.keys():
            if not is_tracking_active(wallet):
                response += f"⏳ Not currently within tracking period for {wallet}. Skipping.\n"
                continue

            # Fetch wallet transactions
            txs_url = f"https://mempool.space/api/address/{wallet}/txs/mempool"
            txs_info = await HTTPSession.get_json_response(txs_url)

            if not txs_info or len(txs_info) == 0:
                response += f"✅ No new transactions for `{wallet}`.\n"
                continue

            latest_tx_hash = txs_info[0]["txid"]
            if wallet in seen_transactions and latest_tx_hash in seen_transactions[wallet]:
                response += f"🟡 No new transactions for `{wallet}`.\n"
                continue

            # New transaction detected
            if wallet not in seen_transactions:
                seen_transactions[wallet] = set()
            seen_transactions[wallet].add(latest_tx_hash)

            response += f"⚡ New transaction detected for `{wallet}`! Checking balance...\n"

            # Fetch wallet balance
            wallet_balance = await return_balance(wallet)
            if wallet_balance is None:
                response += f"❌ Error retrieving balance for `{wallet}`.\n"
                continue

            # Get threshold for the wallet
            threshold = wallet_settings[wallet].get("threshold", 0.01)  # Default threshold

            # Send alert if balance drops below threshold
            if wallet_balance < threshold:
                response += f"⚠️ Balance Alert! `{wallet}` balance dropped below `{threshold}` BTC to `{wallet_balance:.8f}` BTC.\n"

        # Send the response to the user
        # await bot.send_message(chat_id, response)
        print(response)

        # Wait 30 seconds before checking again
        await asyncio.sleep(30)

    # Stop tracking if user exits tracking state
    await bot.set_state(user_id, "menu")
    await bot.send_message(chat_id, "Tracking stopped.", reply_markup=keyboards["menu"])


# MESSAGE HANDLERS



@bot.message_handler(commands=["start"])
async def welcome(msg):
    await bot.set_state(msg.from_user.id, "menu")
    await bot.reset_data(msg.from_user.id)
    await bot.send_message(msg.chat.id, text="Hello", reply_markup=keyboards["menu"])


@bot.message_handler(text_startswith=icons["cancel"])
async def btn_cancel(msg):
    await bot.set_state(msg.from_user.id, "menu")
    await bot.send_message(msg.chat.id, text=icons["cancel"], reply_markup=keyboards["menu"])


@bot.message_handler(commands=["debug"])
async def debug(msg):
    async with bot.retrieve_data(msg.from_user.id) as data:
        state = await bot.get_state(msg.from_user.id)
        print(f"DEBUG INFO\nUser state: {state}\nUser Data: {data}")
    await bot.delete_message(msg.chat.id, msg.message_id)


@bot.message_handler(text_startswith=icons["wallet"])
async def btn_wallet(msg):
    async with bot.retrieve_data(msg.from_user.id) as data:
        if data is None or (wallet := data.get("wallet")) is None:
            response = "BTC wallet is not set"
        else:
            response = f"BTC Wallet:\n{wallet}"
    await bot.send_message(msg.chat.id, text=response, reply_markup=keyboards["wallet"])

@bot.callback_query_handler(func=lambda call: call.data == "check_balance", state="menu")
async def check_balance(call):
    # Load wallet settings from JSON file
    wallet_settings = load_wallet_settings()
    
    if not wallet_settings:
        await bot.send_message(call.message.chat.id, "No wallets found in records. Please add one.")
        return

    response = "💰 **Wallet Balances:**\n"
    
    for wallet in wallet_settings.keys():  # Iterate over all wallets
        # Fetch wallet info from Mempool API
        wallet_info = await HTTPSession.get_json_response(f"https://mempool.space/api/address/{wallet}")

        if not wallet_info:
            response += f"❌ Could not fetch balance for {wallet}.\n"
            continue

        # Extract balance details
        funded_txo_sum = wallet_info["chain_stats"].get("funded_txo_sum", 0)
        spent_txo_sum = wallet_info["chain_stats"].get("spent_txo_sum", 0)
        mempool_funded = wallet_info["mempool_stats"].get("funded_txo_sum", 0)  # Unconfirmed incoming
        mempool_spent = wallet_info["mempool_stats"].get("spent_txo_sum", 0)  # Unconfirmed outgoing
        tx_count = wallet_info["chain_stats"].get("tx_count", 0)

        # Calculate total balance (confirmed + unconfirmed)
        confirmed_balance = (funded_txo_sum - spent_txo_sum) / 100_000_000  # BTC
        mempool_balance = (mempool_funded - mempool_spent) / 100_000_000  # BTC
        total_balance = confirmed_balance + mempool_balance  # Include unconfirmed tx

        response += (
            f"🔹 **Wallet:** `{wallet}`\n"
            f"✅ Confirmed: `{confirmed_balance:.8f} BTC`\n"
            f"⏳ Unconfirmed: `{mempool_balance:.8f} BTC`\n"
            f"💳 **Total:** `{total_balance:.8f} BTC`\n"
            f"📜 Transactions: `{tx_count}`\n\n"
        )

    await bot.send_message(call.message.chat.id, text=response)
    

@bot.message_handler(text_startswith=icons["start_tracking"], state="menu")
async def btn_start_tracking(msg):
    # Load wallet settings from JSON file
    wallet_settings = load_wallet_settings()

    # Check if the user has a wallet stored
    user_wallet = None
    for wallet, details in wallet_settings.items():
        if "start_date" in details and "end_date" in details and "threshold" in details:
            user_wallet = wallet
            break  # Use the first found wallet (or modify logic to support multiple)

    if user_wallet is None:
        await bot.send_message(msg.chat.id, text="No wallet found in records. Please add one.", reply_markup=keyboards["set_wallet"])
        return

    await bot.set_state(msg.from_user.id, "tracking")
    await start_tracking(msg.chat.id, msg.from_user.id, user_wallet)


@bot.message_handler(text_startswith=icons["stop_tracking"], state="tracking")
async def btn_stop_tracking(msg):
    await bot.set_state(msg.from_user.id, "menu")
    await bot.send_message(msg.chat.id, text="Transaction tracking off", reply_markup=keyboards["menu"])

@bot.callback_query_handler(func=lambda call: call.data == "set_new_wallet", state="menu")
async def btn_set_wallet(call):
    await bot.set_state(call.from_user.id, "wallet_query")
    await bot.send_message(call.message.chat.id, text="Enter new wallet", reply_markup=keyboards["query"])


@bot.message_handler(state="wallet_query")
async def wallet_query(msg):
    """Handles new wallet entry and starts the update process."""
    wallet_address = msg.text.strip().removeprefix("bitcoin:")

    if not re.fullmatch(r"^([13]{1}[a-km-zA-HJ-NP-Z1-9]{26,33}|bc1[a-z0-9]{39,59})$", wallet_address):
        await bot.send_message(msg.chat.id, text="❌ Invalid BTC wallet. Try again.")
        return
    
    if wallet_address not in wallet_settings:
        wallet_settings[wallet_address] = {}  # Create new entry
    # Temporarily store the wallet in user session
    await bot.add_data(msg.from_user.id, wallet=wallet_address)

    # Ask for start date
    await bot.set_state(msg.from_user.id, "awaiting_start_date")
    await bot.send_message(msg.chat.id, "📅 Enter tracking start date (YYYY-MM-DD):", reply_markup=keyboards["query"])


@bot.message_handler(state="awaiting_start_date")
async def process_start_date(msg):
    print(f"Received start date: {msg.text}")  # Debugging
    """Handles user input for tracking start date."""
    async with bot.retrieve_data(msg.from_user.id) as data:
        wallet = data.get("wallet")
    print(f"start date wallet: {wallet}")  # Debugging
    start_date = msg.text.strip()
    
    print(f"start date start_date: {start_date}")  # Debugging
    # Validate date format
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        await bot.send_message(msg.chat.id, "❌ Invalid date format! Enter date as YYYY-MM-DD.")
        return

    await bot.add_data(msg.from_user.id, start_date=start_date)

    await bot.set_state(msg.from_user.id, "awaiting_end_date")
    await bot.send_message(msg.chat.id, "📅 Enter tracking end date (YYYY-MM-DD):", reply_markup=keyboards["query"])

@bot.message_handler(state="awaiting_end_date")
async def process_end_date(msg):
    """Handles user input for tracking end date."""
    async with bot.retrieve_data(msg.from_user.id) as data:
        wallet = data.get("wallet")
        start_date = data.get("start_date")
    
    print(f"end_date wallet and start_date: {wallet} + {start_date}")  # Debugging

    end_date = msg.text.strip()

    # Validate date format
    try:
        datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        await bot.send_message(msg.chat.id, "❌ Invalid date format! Enter date as YYYY-MM-DD.")
        return

    # Ensure end date is after start date
    if end_date < start_date:
        await bot.send_message(msg.chat.id, "❌ End date must be after start date!")
        return

    await bot.add_data(msg.from_user.id, end_date=end_date)

    await bot.set_state(msg.from_user.id, "awaiting_threshold")
    await bot.send_message(msg.chat.id, "🔢 Enter balance threshold (BTC) for alerts:", reply_markup=keyboards["query"])

@bot.message_handler(state="awaiting_threshold")
async def process_threshold(msg):
    """Handles user input for balance threshold and saves everything to JSON."""
    async with bot.retrieve_data(msg.from_user.id) as data:
        wallet = data.get("wallet")
        start_date = data.get("start_date")
        end_date = data.get("end_date")

    try:
        threshold = float(msg.text.strip())
    except ValueError:
        await bot.send_message(msg.chat.id, "❌ Invalid number! Enter a numeric BTC value.")
        return

    # Store wallet details in persistent JSON storage
    wallet_settings[wallet] = {
        "start_date": start_date,
        "end_date": end_date,
        "threshold": threshold
    }

    save_wallet_settings()  # Save the updated settings

    await bot.set_state(msg.from_user.id, "menu")
    await bot.send_message(msg.chat.id, f"✅ Wallet {wallet} has been successfully added!\n"
                                        f"📅 Start Date: {start_date}\n"
                                        f"📅 End Date: {end_date}\n"
                                        f"⚠️ Alert if balance drops below {threshold} BTC.", reply_markup=keyboards["menu"])


@bot.message_handler(func=lambda msg: msg.text[0] in icons.values())
async def wrong_command(msg):
    await bot.set_state(msg.from_user.id, "menu")
    await bot.send_message(msg.chat.id, text="Invalid command.\nGoing back to menu...",
                           reply_markup=keyboards["menu"])

@bot.message_handler(func=lambda msg: True)#Keep this at the very bottom because it only detects unrecognized messages because it is at the bottom.
async def delete_unrecognized(msg):
    print(f"delete unrecognized")  # Debugging
    await bot.delete_message(msg.chat.id, msg.message_id)

if __name__ == "__main__":
    asyncio.run(bot.infinity_polling())


