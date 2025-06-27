# MiNightUnlocker



>  Telegram bot that automatically submits a Xiaomi bootloader unlock request exactly at 00:00 China Standard Time (CST).  

## ✨ Features

- Telegram bot that automates token extraction and bootloader unlock application submission
- Sends application exactly at 00:00 China Standard Time (CST)
- Supports manual unlock attempts on demand
- Provides token-only extraction option (use /test)
- Encrypts password data securely using Fernet

## 📦 Requirements
- Python 3.11 or newer
- [Playwright](https://playwright.dev/python/) with Chromium and Firefox
- Packages listed in `requirements.txt

## ⚙️ Installation
```
git clone https://github.com/your-username/MiNightUnlocker.git
cd MiNightUnlocker
pip install -r requirements.txt
playwright install chromium firefox
```
## ✅ Instruction

__1\.__ 🔑**Generate an encryption key** to protect user passwords:
    Run this command in your terminal or command prompt:
   ```
   python generate_key.py
   ```
___⚠️ Important: You must save the generated encryption key in a secure place.
Without this key, it will be impossible to access or decrypt the data of existing users, and the bot will not function properly.___

__2\.__ Create .env file in the main project folder with your configuration:
```
BOT_TOKEN=your_telegram_bot_token
ACCESS_CODE=optional_code_for_user_verification
```

💡 Optional:
If you set ACCESS_CODE=RANDOM in your .env file, the bot will generate a random 8-character access code on startup and display it in the console.
Make sure to check the console output to get the generated code for user authorization.


🚀Start the bot:
```
- python bot.py
```
ℹ️  ___When starting the bot, you will be prompted to enter the encryption key each time.  
Make sure to keep this key secure and accessible, as it is required for the bot to access encrypted data.___






