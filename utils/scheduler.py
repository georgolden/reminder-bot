"""
APScheduler wrapper for reminder scheduling.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from typing import Callable, Any
import pytz
import asyncio

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """Get the scheduler instance."""
    global _scheduler
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialized. Call init_scheduler() first.")
    return _scheduler


def init_scheduler() -> AsyncIOScheduler:
    """Initialize the scheduler with asyncio support."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
        try:
            _scheduler.start()
        except RuntimeError:
            # If no running loop, start with the current loop (python-telegram-bot creates it later)
            loop = asyncio.get_event_loop()
            _scheduler.start(loop)
        print("[Scheduler] Initialized and started")
    return _scheduler


def shutdown_scheduler():
    """Shutdown the scheduler gracefully."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=True)
        _scheduler = None
        print("[Scheduler] Shutdown complete")


def schedule_once(
    job_id: str,
    run_date: datetime | str,
    callback: Callable,
    timezone: str = "UTC",
    **kwargs: Any
) -> str:
    """
    Schedule a one-time job.
    
    Args:
        job_id: Unique identifier for the job
        run_date: When to run (datetime or ISO string)
        callback: Async function to call
        timezone: IANA timezone string
        **kwargs: Additional arguments passed to callback
    
    Returns:
        job_id
    """
    scheduler = get_scheduler()
    
    # Parse datetime if string
    if isinstance(run_date, str):
        run_date = datetime.fromisoformat(run_date.replace('Z', '+00:00'))
    
    # Apply timezone if naive datetime
    tz = pytz.timezone(timezone)
    if run_date.tzinfo is None:
        run_date = tz.localize(run_date)
    
    trigger = DateTrigger(run_date=run_date, timezone=tz)
    
    scheduler.add_job(
        callback,
        trigger=trigger,
        id=job_id,
        kwargs=kwargs,
        replace_existing=True
    )
    
    print(f"[Scheduler] Scheduled one-time job '{job_id}' for {run_date}")
    return job_id


def schedule_cron(
    job_id: str,
    cron_expression: str,
    callback: Callable,
    timezone: str = "UTC",
    end_date: datetime | str | None = None,
    **kwargs: Any
) -> str:
    """
    Schedule a recurring job using cron expression.
    
    Args:
        job_id: Unique identifier for the job
        cron_expression: 5-field cron expression (minute hour day month weekday)
        callback: Async function to call
        timezone: IANA timezone string
        end_date: Optional end datetime to auto-stop the cron
        **kwargs: Additional arguments passed to callback
    
    Returns:
        job_id
    """
    scheduler = get_scheduler()
    
    # Parse cron expression (5 fields: minute hour day month day_of_week)
    parts = cron_expression.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: expected 5 fields, got {len(parts)}")
    
    minute, hour, day, month, day_of_week = parts
    
    tz = pytz.timezone(timezone)
    
    # Handle end_date
    parsed_end_date = None
    if end_date:
        if isinstance(end_date, str):
            parsed_end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        else:
            parsed_end_date = end_date
        if parsed_end_date.tzinfo is None:
            parsed_end_date = tz.localize(parsed_end_date)
    
    trigger = CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        timezone=tz,
        end_date=parsed_end_date
    )
    
    scheduler.add_job(
        callback,
        trigger=trigger,
        id=job_id,
        kwargs=kwargs,
        replace_existing=True
    )
    
    end_info = f" (ends: {parsed_end_date})" if parsed_end_date else ""
    print(f"[Scheduler] Scheduled cron job '{job_id}' with expression '{cron_expression}'{end_info}")
    return job_id


def remove_job(job_id: str) -> bool:
    """
    Remove a scheduled job.
    
    Returns:
        True if job was removed, False if not found
    """
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(job_id)
        print(f"[Scheduler] Removed job '{job_id}'")
        return True
    except Exception:
        print(f"[Scheduler] Job '{job_id}' not found")
        return False


if __name__ == "__main__":
    import asyncio
    
    async def test_callback(**kwargs):
        print(f"[Test] Callback fired with: {kwargs}")
    
    async def main():
        init_scheduler()
        
        # Test one-time schedule (5 seconds from now)
        from datetime import timedelta
        run_at = datetime.now() + timedelta(seconds=5)
        schedule_once("test-once", run_at, test_callback, reminder_text="Test reminder")
        
        print("Waiting for job to fire...")
        await asyncio.sleep(10)
        
        shutdown_scheduler()
    
    asyncio.run(main())
