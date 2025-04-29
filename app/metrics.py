from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import logging
from collections import defaultdict


from app.utils import setup_logging


setup_logging()
logger = logging.getLogger(__name__)


def parse_jira_datetime(date_str: str) -> datetime:
   """Convert Jira datetime string to Python datetime object"""
   # return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
   return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f%z")


def calculate_time_in_progress(changelog: Dict[str, Any]) -> float:
   """
   Calculate the total time a ticket spent in the "In Progress" status.
   Returns time in hours.
   """
   total_time_seconds = 0
   in_progress_start = None


   histories = sorted(
       changelog.get("changelog", {}).get("histories", []),
       key=lambda h: h["created"]
   )


   for history in histories:
       history_created = parse_jira_datetime(history["created"])
       logger.info(f"history Created,{history_created}")


       for item in history.get("items", []):
           if item["field"] != "status":
               continue


           # Transition TO "In Progress"
           if item["toString"] == "In Progress":
               if in_progress_start is None:
                   in_progress_start = history_created
                   logger.info(f"history inprogress,{in_progress_start}")


           # Transition FROM "In Progress"
           elif item["fromString"] == "In Progress" and in_progress_start:
               elapsed = (history_created - in_progress_start).total_seconds()
               logger.info(f"{history_created}: In Progress → {item['toString']}, elapsed {elapsed / 3600:.2f} hours")
               total_time_seconds += elapsed
               in_progress_start = None


   # Still in progress?
   if in_progress_start:
       now = datetime.now().astimezone()
       elapsed = (now - in_progress_start).total_seconds()
       logger.info(f"Still in progress since {in_progress_start} to {now}, adding {elapsed / 3600:.2f} hours")
       total_time_seconds += elapsed


   return total_time_seconds / 3600


def calculate_time_in_review(changelog: Dict[str, Any]) -> float:
   """
   Calculate the total time a ticket spent in the "In Review" status (case-insensitive)


   Returns time in hours
   """
   total_time_seconds = 0
   in_review_start = None


   def is_in_review(status: str) -> bool:
       return status and status.strip().lower() == "in review"
   histories = sorted(
       changelog.get("changelog", {}).get("histories", []),
       key=lambda h: h["created"]
   )
   # Extract status transitions from the changelog
   for history in histories:
       history_created = parse_jira_datetime(history["created"])
       logger.info(f"history Created,{history_created}")


       for item in history.get("items", []):
           if item["field"] == "status":
               from_status = item.get("fromString")
               to_status = item.get("toString")


               logger.info(f"{history_created}: {from_status} → {to_status}")


               # If status changed TO "In Review"
               if is_in_review(to_status):
                   if in_review_start is None:
                       in_review_start = history_created
                       logger.debug(f"Entered 'In Review' at {in_review_start}")


               # If status changed FROM "In Review"
               elif is_in_review(from_status) and in_review_start:
                   elapsed = (history_created - in_review_start).total_seconds()
                   total_time_seconds += elapsed
                   logger.info(f"{history_created}: {from_status} → {to_status}, elapsed {elapsed / 3600:.2f} hours")
                   in_review_start = None


   # If ticket is still in review, calculate time until now
   if in_review_start:
       elapsed = (datetime.now().astimezone() - in_review_start).total_seconds()
       logger.info(f"Still in review, adding time till now: {elapsed} seconds")
       total_time_seconds += elapsed


   # Convert to human-readable format
   if total_time_seconds >= 3600:
       hours = total_time_seconds / 3600
       result = hours
   else:
       minutes = total_time_seconds / 60
       result = minutes
   logger.info(f"Total time in 'In Review': {result}")
   return result


def calculate_lead_time(issue: Dict[str, Any]) -> float:
   """
   Calculate the total lead time from ticket creation to completion
  
   Returns time in hours
   """
   created_date = parse_jira_datetime(issue["fields"]["created"])
  
   # Find when the ticket was moved to Done
   done_date = None
   for history in issue.get("changelog", {}).get("histories", []):
       for item in history.get("items", []):
           if item["field"] == "status" and item["toString"] == "Done":
               done_date = parse_jira_datetime(history["created"])
               break
       if done_date:
           break
  
   # If not done yet, return None
   if not done_date:
       return None
  
   # Calculate total time in hours
   lead_time_seconds = (done_date - created_date).total_seconds()
   return lead_time_seconds / 3600


def get_issue_completion_date(issue: Dict[str, Any]) -> Optional[datetime]:
    """Get the date when the issue was marked as Done"""
    for history in issue.get("changelog", {}).get("histories", []):
        for item in history.get("items", []):
            if item["field"] == "status" and item["toString"] == "Done":
                return parse_jira_datetime(history["created"])
    return None


def get_issue_creation_date(issue: Dict[str, Any]) -> datetime:
    """Get the date when the issue was created"""
    return parse_jira_datetime(issue["fields"]["created"])


def format_period_key(date: datetime, period_type: str) -> str:
    """Format a datetime into a period key string"""
    if period_type == "yearly":
        return date.strftime("%Y")
    elif period_type == "monthly":
        return date.strftime("%Y-%m")
    elif period_type == "weekly":
        # ISO week with year
        return f"{date.isocalendar()[0]}-W{date.isocalendar()[1]:02d}"
    elif period_type == "daily":
        return date.strftime("%Y-%m-%d")
    return ""


def round_metrics(metrics_dict: Dict) -> Dict:
    """Round floating point metrics to 2 decimal places"""
    for key, value in metrics_dict.items():
        if isinstance(value, float):
            metrics_dict[key] = round(value, 2)
    return metrics_dict


def calculate_averages(metrics_list: List[Dict]) -> Dict:
    """Calculate average metrics from a list of metric dictionaries"""
    if not metrics_list:
        return {
            "ticket_count": 0,
            "avg_time_in_progress_hours": 0,
            "avg_time_in_review_hours": 0,
            "avg_lead_time_hours": 0,
            "avg_time_in_progress_days": 0,
            "avg_time_in_review_days": 0,
            "avg_lead_time_days": 0,
        }
    
    total_tickets = len(metrics_list)
    valid_progress = [m["time_in_progress_hours"] for m in metrics_list if m.get("time_in_progress_hours")]
    valid_review = [m["time_in_review_hours"] for m in metrics_list if m.get("time_in_review_hours")]
    valid_lead = [m["lead_time_hours"] for m in metrics_list if m.get("lead_time_hours")]
    
    avg_progress = sum(valid_progress) / len(valid_progress) if valid_progress else 0
    avg_review = sum(valid_review) / len(valid_review) if valid_review else 0
    avg_lead = sum(valid_lead) / len(valid_lead) if valid_lead else 0
    
    return {
        "ticket_count": total_tickets,
        "avg_time_in_progress_hours": round(avg_progress, 2),
        "avg_time_in_review_hours": round(avg_review, 2),
        "avg_lead_time_hours": round(avg_lead, 2),
        "avg_time_in_progress_days": round(avg_progress / 24, 2),
        "avg_time_in_review_days": round(avg_review / 24, 2),
        "avg_lead_time_days": round(avg_lead / 24, 2),
    }


def ensure_timezone_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure a datetime is timezone-aware by adding UTC timezone if needed"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Add UTC timezone if timezone is not specified
        return dt.replace(tzinfo=timezone.utc)
    return dt


def aggregate_metrics_by_period(
    issues: List[Dict[str, Any]], 
    start_date: Optional[datetime] = None, 
    end_date: Optional[datetime] = None
) -> Dict[str, List[Dict]]:
    """
    Aggregate ticket metrics by different time periods (yearly, monthly, weekly, daily)
    
    Args:
        issues: List of issue data dictionaries with changelog
        start_date: Optional start date for filtering
        end_date: Optional end date for filtering
        
    Returns:
        Dictionary with aggregated metrics by different time periods
    """
    # Make sure start_date and end_date are timezone-aware
    start_date = ensure_timezone_aware(start_date)
    end_date = ensure_timezone_aware(end_date)
    
    # Initialize containers for each period type
    yearly_metrics = defaultdict(list)
    monthly_metrics = defaultdict(list)
    weekly_metrics = defaultdict(list)
    daily_metrics = defaultdict(list)
    
    # Process each issue and calculate metrics
    for issue in issues:
        # Calculate individual metrics
        time_in_progress = calculate_time_in_progress(issue)
        time_in_review = calculate_time_in_review(issue)
        lead_time = calculate_lead_time(issue)
        
        # Skip issues without valid metrics
        if lead_time is None:
            continue
            
        # Get creation and completion dates
        created_date = get_issue_creation_date(issue)
        completion_date = get_issue_completion_date(issue)
        
        if not completion_date:
            continue
            
        # Apply date filtering if specified
        if start_date and completion_date < start_date:
            continue
        if end_date and completion_date > end_date:
            continue
            
        # Create metrics dict for this issue
        metrics_dict = {
            "ticket_key": issue["key"],
            "time_in_progress_hours": time_in_progress,
            "time_in_review_hours": time_in_review,
            "lead_time_hours": lead_time
        }
        
        # Add to appropriate period buckets based on completion date
        yearly_key = format_period_key(completion_date, "yearly")
        monthly_key = format_period_key(completion_date, "monthly")
        weekly_key = format_period_key(completion_date, "weekly")
        daily_key = format_period_key(completion_date, "daily")
        
        yearly_metrics[yearly_key].append(metrics_dict)
        monthly_metrics[monthly_key].append(metrics_dict)
        weekly_metrics[weekly_key].append(metrics_dict)
        daily_metrics[daily_key].append(metrics_dict)
    
    # Calculate aggregated metrics for each period
    yearly_results = []
    monthly_results = []
    weekly_results = []
    daily_results = []
    
    # Process yearly metrics
    for period, metrics in sorted(yearly_metrics.items()):
        avg_metrics = calculate_averages(metrics)
        yearly_results.append({
            "period": period,
            **avg_metrics
        })
    
    # Process monthly metrics
    for period, metrics in sorted(monthly_metrics.items()):
        avg_metrics = calculate_averages(metrics)
        monthly_results.append({
            "period": period,
            **avg_metrics
        })
    
    # Process weekly metrics
    for period, metrics in sorted(weekly_metrics.items()):
        avg_metrics = calculate_averages(metrics)
        weekly_results.append({
            "period": period,
            **avg_metrics
        })
    
    # Process daily metrics
    for period, metrics in sorted(daily_metrics.items()):
        avg_metrics = calculate_averages(metrics)
        daily_results.append({
            "period": period,
            **avg_metrics
        })
    
    return {
        "yearly": yearly_results,
        "monthly": monthly_results,
        "weekly": weekly_results,
        "daily": daily_results
    }