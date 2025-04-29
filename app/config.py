import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    JIRA_URL = os.getenv("JIRA_URL", "https://your-domain.atlassian.net")
    JIRA_EMAIL = os.getenv("JIRA_EMAIL")
    JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
    
    # Status mapping - adjust according to your workflow
    STATUS_IN_PROGRESS = "In Progress"
    STATUS_IN_REVIEW = "In Review"
    STATUS_DONE = "Done"

settings = Settings()