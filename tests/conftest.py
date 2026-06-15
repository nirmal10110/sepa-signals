import matplotlib
matplotlib.use("Agg")

# Prevent tests from touching live external services.
# The .env file may contain real credentials; tests must never hit the real APIs.
import os
os.environ["TELEGRAM_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""   # validator falls back to CAUTION on empty key
