import logging
from app.jira_client import JiraClient
from app.metrics import (
    calculate_lead_time, 
    calculate_time_in_progress, 
    calculate_time_in_review,
    aggregate_metrics_by_period,
    ensure_timezone_aware
)
from fastapi import FastAPI, HTTPException, Depends, Query
from typing import List, Optional, Dict, Any
import uvicorn
from datetime import datetime
from enum import Enum


from app.config import settings
from pydantic import BaseModel
from app.utils import setup_logging


setup_logging()
logger = logging.getLogger(__name__)
app = FastAPI(title="Developer Productivity Metrics API")


class TicketMetrics(BaseModel):
   ticket_key: str
   time_in_progress_hours: Optional[float] = None
   time_in_review_hours: Optional[float] = None
   lead_time_hours: Optional[float] = None


class MetricsSummary(BaseModel):
   assignee_name: Optional[str] = None
   ticket_count: int
   start_date: Optional[datetime] = None
   end_date: Optional[datetime] = None
   avg_time_in_progress_hours: float
   avg_time_in_review_hours: float
   avg_lead_time_hours: float
   avg_time_in_progress_days: float
   avg_time_in_review_days: float
   avg_lead_time_days: float


class TimeBasedMetrics(BaseModel):
    period: str
    ticket_count: int
    avg_time_in_progress_hours: float
    avg_time_in_review_hours: float
    avg_lead_time_hours: float
    avg_time_in_progress_days: float
    avg_time_in_review_days: float
    avg_lead_time_days: float


class AggregatedMetrics(BaseModel):
    yearly: List[TimeBasedMetrics] = []
    monthly: List[TimeBasedMetrics] = []
    weekly: List[TimeBasedMetrics] = []
    daily: List[TimeBasedMetrics] = []


class PeriodType(str, Enum):
    YEARLY = "yearly"
    MONTHLY = "monthly" 
    WEEKLY = "weekly"
    DAILY = "daily"
    ALL = "all"


class MetricsResponse(BaseModel):
   tickets: List[TicketMetrics]
   summary: MetricsSummary
   time_based_metrics: Optional[AggregatedMetrics] = None


def get_jira_client():
   return JiraClient()


@app.get("/metrics/ticket/{ticket_key}", response_model=TicketMetrics)
async def get_ticket_metrics(ticket_key: str, jira_client: JiraClient = Depends(get_jira_client)):
   try:
       # Get issue with changelog
       issue_data = jira_client.get_issue_changelog(ticket_key)
      
       # Calculate metrics
       time_in_progress = calculate_time_in_progress(issue_data)
       time_in_review = calculate_time_in_review(issue_data)
       lead_time = calculate_lead_time(issue_data)
      
       return TicketMetrics(
           ticket_key=ticket_key,
           time_in_progress_hours=time_in_progress,
           time_in_review_hours=time_in_review,
           lead_time_hours=lead_time
       )
   except Exception as e:
       raise HTTPException(status_code=500, detail=f"Error calculating metrics: {str(e)}")


@app.get("/metrics/project/{project_key}")
async def get_project_metrics(
   project_key: str,
   days: int = 30,
   jira_client: JiraClient = Depends(get_jira_client)
):
   try:
       # Search for completed tickets in the last X days
       jql = f"project = {project_key} AND status changed to Done during (-{days}d, now())"
       issues = jira_client.search_issues(jql)
       logger.info(f"search results,{issues}")
      
       results = []
       for issue in issues.get("issues", []):
           # Get full issue data with changelog
           issue_data = jira_client.get_issue_changelog(issue["key"])
          
           # Calculate metrics
           metrics = TicketMetrics(
               ticket_key=issue["key"],
               time_in_progress_hours=calculate_time_in_progress(issue_data),
               time_in_review_hours=calculate_time_in_review(issue_data),
               lead_time_hours=calculate_lead_time(issue_data)
           )
           results.append(metrics.dict())
      
       # Calculate averages
       if results:
           avg_progress = sum(r["time_in_progress_hours"] for r in results if r["time_in_progress_hours"]) / len(results)
           avg_review = sum(r["time_in_review_hours"] for r in results if r["time_in_review_hours"]) / len(results)
           avg_lead = sum(r["lead_time_hours"] for r in results if r["lead_time_hours"]) / len(results)
       else:
           avg_progress = avg_review = avg_lead = 0
      
       return {
           "tickets": results,
           "summary": {
               "ticket_count": len(results),
               "avg_time_in_progress_hours": round(avg_progress, 2),
               "avg_time_in_review_hours": round(avg_review, 2),
               "avg_lead_time_hours": round(avg_lead, 2),
               "avg_time_in_progress_days": round(avg_progress / 24, 2),
               "avg_time_in_review_days": round(avg_review / 24, 2),
               "avg_lead_time_days": round(avg_lead / 24, 2)
           }
       }
   except Exception as e:
       raise HTTPException(status_code=500, detail=f"Error calculating project metrics: {str(e)}")


@app.get("/metrics/project/{project_key}/filtered", response_model=MetricsResponse)
async def get_filtered_project_metrics(
   project_key: str,
   assignee: Optional[str] = Query(None, description="Filter by assignee name"),
   task_type: Optional[str] = Query(None, description="Filter by task type (e.g., Bug, Feature, Task)"),
   start_date: Optional[datetime] = Query(None, description="Start date for filtering (YYYY-MM-DD)"),
   end_date: Optional[datetime] = Query(None, description="End date for filtering (YYYY-MM-DD)"),
   period: Optional[PeriodType] = Query(PeriodType.ALL, description="Time period for aggregation (yearly, monthly, weekly, daily, all)"),
   jira_client: JiraClient = Depends(get_jira_client)
):
   try:
       # Ensure dates are timezone-aware
       start_date = ensure_timezone_aware(start_date)
       end_date = ensure_timezone_aware(end_date)
       
       # Build JQL query with filters
       jql_parts = [f"project = {project_key}"]
      
       if assignee:
           jql_parts.append(f'assignee = "{assignee}"')
      
       if task_type:
           jql_parts.append(f'type = "{task_type}"')
      
       if start_date:
           jql_parts.append(f'created >= "{start_date.strftime("%Y-%m-%d")}"')
      
       if end_date:
           jql_parts.append(f'created <= "{end_date.strftime("%Y-%m-%d")}"')
      
       jql = " AND ".join(jql_parts)
       logger.info(f"Executing JQL: {jql}")
      
       # Search for tickets matching the criteria
       issues = jira_client.search_issues(jql)
      
       results = []
       issue_data_list = []
       for issue in issues.get("issues", []):
           # Get full issue data with changelog
           issue_data = jira_client.get_issue_changelog(issue["key"])
           issue_data_list.append(issue_data)
          
           # Calculate metrics
           metrics = TicketMetrics(
               ticket_key=issue["key"],
               time_in_progress_hours=calculate_time_in_progress(issue_data),
               time_in_review_hours=calculate_time_in_review(issue_data),
               lead_time_hours=calculate_lead_time(issue_data)
           )
           results.append(metrics.dict())
      
       # Calculate summary statistics
       if results:
           valid_progress = [r["time_in_progress_hours"] for r in results if r["time_in_progress_hours"]]
           avg_progress = sum(valid_progress) / len(valid_progress) if valid_progress else 0

           valid_review = [r["time_in_review_hours"] for r in results if r["time_in_review_hours"]]
           avg_review = sum(valid_review) / len(valid_review) if valid_review else 0

           valid_lead = [r["lead_time_hours"] for r in results if r["lead_time_hours"]]
           avg_lead = sum(valid_lead) / len(valid_lead) if valid_lead else 0
       else:
           avg_progress = avg_review = avg_lead = 0
      
       summary = MetricsSummary(
           assignee_name=assignee,
           ticket_count=len(results),
           start_date=start_date,
           end_date=end_date,
           avg_time_in_progress_hours=round(avg_progress, 2),
           avg_time_in_review_hours=round(avg_review, 2),
           avg_lead_time_hours=round(avg_lead, 2),
           avg_time_in_progress_days=round(avg_progress / 24, 2),
           avg_time_in_review_days=round(avg_review / 24, 2),
           avg_lead_time_days=round(avg_lead / 24, 2)
       )
       
       response = MetricsResponse(
           tickets=results,
           summary=summary
       )
       
       # Generate time-based metrics if requested
       if period != PeriodType.ALL and issue_data_list:
           time_metrics = aggregate_metrics_by_period(
               issue_data_list,
               start_date=start_date,
               end_date=end_date
           )
           
           response.time_based_metrics = time_metrics
      
       return response
   except Exception as e:
       logger.error(f"Error calculating filtered metrics: {str(e)}")
       raise HTTPException(status_code=500, detail=f"Error calculating filtered metrics: {str(e)}")


if __name__ == "__main__":
   uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)