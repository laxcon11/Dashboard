from datetime import datetime, timedelta
import pandas as pd

def is_monthly_expiry(expiry_date: str | datetime) -> bool:
    """
    NSE Monthly expiries are always the last Thursday of the month.
    """
    if isinstance(expiry_date, str):
        try:
            dt = datetime.strptime(expiry_date, "%d-%b-%Y")
        except ValueError:
            return False # Fallback for invalid formats like 'UNKNOWN_0'
    else:
        dt = expiry_date
        
    # NSE Monthly expiries are the last Thursday of the month
    if dt.weekday() != 3:
        return False
        
    next_thurs = dt + timedelta(days=7)
    # If the next Thursday is in a different month, it's the last Thursday
    return next_thurs.month != dt.month

def get_expiry_type(expiry_date: str | datetime) -> str:
    """Returns 'MONTHLY' or 'WEEKLY' based on the date."""
    return "MONTHLY" if is_monthly_expiry(expiry_date) else "WEEKLY"

def sort_expiries(expiries: list[str]) -> list[str]:
    """Sorts a list of DD-Mon-YYYY strings chronologically."""
    def try_parse(x):
        try:
            return datetime.strptime(x, "%d-%b-%Y")
        except:
            return datetime.max
    return sorted(expiries, key=try_parse)
