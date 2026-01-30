"""
JSON file storage for reminder metadata and user preferences.
"""
import json
import os
from typing import TypedDict
from datetime import datetime
import uuid

# Storage file path
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
REMINDERS_FILE = os.path.join(DATA_DIR, "reminders.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")


class Reminder(TypedDict):
    id: str
    user_id: str
    chat_id: str
    text: str
    schedule_type: str  # "once" or "cron"
    schedule_value: str  # ISO datetime or cron expression
    timezone: str
    created_at: str
    active: bool


def _ensure_data_dir():
    """Ensure data directory exists."""
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_reminders() -> dict[str, Reminder]:
    """Load reminders from JSON file."""
    _ensure_data_dir()
    if not os.path.exists(REMINDERS_FILE):
        return {}
    with open(REMINDERS_FILE, "r") as f:
        return json.load(f)


def _save_reminders(reminders: dict[str, Reminder]):
    """Save reminders to JSON file."""
    _ensure_data_dir()
    with open(REMINDERS_FILE, "w") as f:
        json.dump(reminders, f, indent=2)


def generate_reminder_id() -> str:
    """Generate a short unique ID for a reminder."""
    return uuid.uuid4().hex[:8]


def save_reminder(
    user_id: str,
    chat_id: str,
    text: str,
    schedule_type: str,
    schedule_value: str,
    timezone: str = "UTC",
    reminder_id: str | None = None
) -> Reminder:
    """
    Save a new reminder.
    
    Returns:
        The saved reminder with generated ID
    """
    reminders = _load_reminders()
    
    if reminder_id is None:
        reminder_id = generate_reminder_id()
    
    reminder: Reminder = {
        "id": reminder_id,
        "user_id": user_id,
        "chat_id": chat_id,
        "text": text,
        "schedule_type": schedule_type,
        "schedule_value": schedule_value,
        "timezone": timezone,
        "created_at": datetime.utcnow().isoformat(),
        "active": True
    }
    
    reminders[reminder_id] = reminder
    _save_reminders(reminders)
    
    print(f"[Storage] Saved reminder '{reminder_id}': {text[:50]}...")
    return reminder


def get_reminders(user_id: str) -> list[Reminder]:
    """Get all active reminders for a user."""
    reminders = _load_reminders()
    return [
        r for r in reminders.values()
        if r["user_id"] == user_id and r["active"]
    ]


def get_reminder(reminder_id: str) -> Reminder | None:
    """Get a specific reminder by ID."""
    reminders = _load_reminders()
    return reminders.get(reminder_id)


def get_reminder_for_user(reminder_id: str, user_id: str) -> Reminder | None:
    """Get a specific reminder by ID, scoped to a user."""
    reminder = get_reminder(reminder_id)
    if not reminder or not reminder.get("active"):
        return None
    if reminder.get("user_id") != user_id:
        return None
    return reminder


def get_all_reminders() -> list[Reminder]:
    """Get all active reminders (for scheduler restore on startup)."""
    reminders = _load_reminders()
    return [r for r in reminders.values() if r["active"]]


def delete_reminder(reminder_id: str) -> bool:
    """
    Mark a reminder as inactive (soft delete).
    
    Returns:
        True if reminder was found and deleted, False otherwise
    """
    reminders = _load_reminders()
    
    if reminder_id not in reminders:
        print(f"[Storage] Reminder '{reminder_id}' not found")
        return False
    
    reminders[reminder_id]["active"] = False
    _save_reminders(reminders)
    
    print(f"[Storage] Deleted reminder '{reminder_id}'")
    return True


# User preferences

def _load_users() -> dict:
    """Load users from JSON file."""
    _ensure_data_dir()
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r") as f:
        return json.load(f)


def _save_users(users: dict):
    """Save users to JSON file."""
    _ensure_data_dir()
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)


def get_user_timezone(user_id: str) -> str:
    """Get user's preferred timezone. Default: UTC."""
    users = _load_users()
    user = users.get(user_id, {})
    return user.get("timezone", "UTC")


def set_user_timezone(user_id: str, timezone: str):
    """Set user's preferred timezone."""
    users = _load_users()
    if user_id not in users:
        users[user_id] = {}
    users[user_id]["timezone"] = timezone
    _save_users(users)
    print(f"[Storage] Set timezone for user {user_id}: {timezone}")


if __name__ == "__main__":
    # Test storage
    r = save_reminder(
        user_id="123",
        chat_id="456",
        text="Test reminder",
        schedule_type="once",
        schedule_value="2026-01-28T15:00:00",
        timezone="UTC"
    )
    print(f"Created: {r}")
    
    print(f"User reminders: {get_reminders('123')}")
    
    delete_reminder(r["id"])
    print(f"After delete: {get_reminders('123')}")
