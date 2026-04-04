import os
from dotenv import load_dotenv

# Load .env from the same directory as constants.py
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DIRECTOR_ID = 321343879444037633
STUDENT_WORKER_ROLE_ID = 1308228847552041080

PURDUE_CLOCKIN_URL = "https://one.purdue.edu/launch-task/all/webclock"
OPENING_FORM_URL = "https://forms.cloud.microsoft/r/p8Ln3yhHjk"
CLOSING_FORM_URL = "https://forms.cloud.microsoft/r/FVBFhEvfyk"

GGLEAP_API_KEY = os.environ.get("GGLEAP_API_KEY", "")  # Set in .env file
