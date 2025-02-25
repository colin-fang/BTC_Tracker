# Bitcoin Tracker Bot
A Telegram bot that tracks Bitcoin wallet balances and sends alerts when transactions occur or the balance drops below a specified threshold.

## 🚀 Features
✅ Track multiple Bitcoin wallets
✅ Receive alerts via Telegram when a transaction occurs
✅ Supports multiple wallets stored in wallet_settings.json
✅ Check balance manually with a button
✅ Easy setup with virtual environment

## 🚀 Setup Instructions
### 1️⃣ Clone the Repository
`git clone https://github.com/colin-fang/BTC_Tracker.git`
cd BTC_Tracker

### 2️⃣ Set Up Virtual Environment
A virtual environment ensures dependencies don’t interfere with system packages.

Windows

```python -m venv btc_tracker_env

```btc_tracker_env\Scripts\activate

macOS/Linux

```python3 -m venv btc_tracker_env

```source btc_tracker_env/bin/activate

### 3️⃣ Install Dependencies
Install all required Python packages:

pip install -r requirements.txt

If you haven't generated requirements.txt yet, do this:

pip freeze > requirements.txt

### 4️⃣ Create & Configure Required Files
## 📌 Telegram Bot Token
Create a Telegram bot via BotFather and obtain your bot token.
Store the token in a file called token.txt (same directory as main.py).

echo "YOUR_TELEGRAM_BOT_TOKEN" > token.txt

### 5️⃣ Configure wallet_settings.json
This file stores wallets to track and their alert settings.

Example format:

{
    "bc1qexamplewallet1": {
        "start_date": "2024-02-24",
        "end_date": "2025-02-25",
        "threshold": 10.0
    },
    "bc1qexamplewallet2": {
        "start_date": "2024-02-24",
        "end_date": "2025-02-25",
        "threshold": 5.0
    }
}
💡 Fields explained:

"start_date" and "end_date" define when tracking should be active.
"threshold" sets the minimum balance before an alert is sent.
### 6️⃣ Run the Bot
Start the bot with:

python main.py

The bot will now listen for messages and track wallets. 🎯

### 🔧 Additional Configuration
Modify Polling Time
The bot currently checks wallets every 30 seconds.
To modify, change the await asyncio.sleep(30) in poke_blockchain().
### 🛠 Troubleshooting
❌ ModuleNotFoundError: No module named 'aiohttp'
✔️ Install missing dependencies:

pip install aiohttp telebot

❌ Token is invalid
✔️ Ensure token.txt contains the correct Telegram bot token.

❌ Tracking doesn't start
✔️ Make sure wallet_settings.json has at least one valid wallet address.

📜 License
This project is open-source under the MIT License.
