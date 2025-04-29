import requests
from datetime import datetime
import logging


from app.utils import setup_logging
from .config import settings


setup_logging()
class JiraClient:
   def __init__(self, base_url=None, email=None, api_token=None):
       self.logger = logging.getLogger(__name__)
       self.base_url = base_url or settings.JIRA_URL
       self.email = email or settings.JIRA_EMAIL
       self.api_token = api_token or settings.JIRA_API_TOKEN
       self.auth = (self.email, self.api_token)
       self.headers = {
           "Accept": "application/json",
           "Content-Type": "application/json"
       }
      
   def get_issue(self, issue_key):
       """Get basic issue data"""
       url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
       response = requests.get(url, headers=self.headers, auth=self.auth)
       self.logger.info("give",response)
       response.raise_for_status()
       return response.json()
  
   def get_issue_changelog(self, issue_key):
       """Get the complete changelog for an issue"""
       url = f"{self.base_url}/rest/api/3/issue/{issue_key}?expand=changelog"
       response = requests.get(url, headers=self.headers, auth=self.auth)
       response.raise_for_status()
       response1=response.json()
       self.logger.info(f"show,{response1}")
       return response.json()
  
   def search_issues(self, jql, fields=None, max_results=1000):
       """Search for issues using JQL"""
       url = f"{self.base_url}/rest/api/2/search"
       fields = fields or ["key", "summary", "status", "created", "updated"]
       self.logger.info("this is search Issue")
       payload = {
           "jql": jql,
           "maxResults": max_results,
           "fields": fields
       }
      
       response = requests.post(url, json=payload, headers=self.headers, auth=self.auth)
       response.raise_for_status()
       return response.json()