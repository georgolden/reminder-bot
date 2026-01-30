"""
PocketFlow flow for the reminder agent.
"""
from pocketflow import Flow
from nodes import (
    ParseInput,
    DecideAction,
    AskUser,
    ScheduleOnce,
    ScheduleCron,
    ScheduleCronFinite,
    ListReminders,
    CancelReminder,
    CancelAllReminders,
    EditReminder,
    SetTimezone,
    Confirm
)


def create_reminder_flow() -> Flow:
    """Create and return the reminder agent flow."""
    
    # Create nodes
    parse_input = ParseInput()
    decide_action = DecideAction()
    ask_user = AskUser()
    schedule_once = ScheduleOnce()
    schedule_cron = ScheduleCron()
    schedule_cron_finite = ScheduleCronFinite()
    list_reminders = ListReminders()
    cancel_reminder = CancelReminder()
    cancel_all_reminders = CancelAllReminders()
    edit_reminder = EditReminder()
    set_timezone = SetTimezone()
    confirm = Confirm()
    
    # Connect nodes
    # ParseInput -> DecideAction
    parse_input >> decide_action
    
    # DecideAction routes to different actions
    decide_action - "need_info" >> ask_user
    decide_action - "schedule_once" >> schedule_once
    decide_action - "schedule_cron" >> schedule_cron
    decide_action - "schedule_cron_finite" >> schedule_cron_finite
    decide_action - "list" >> list_reminders
    decide_action - "cancel" >> cancel_reminder
    decide_action - "cancel_all" >> cancel_all_reminders
    decide_action - "edit" >> edit_reminder
    decide_action - "set_timezone" >> set_timezone
    
    # AskUser ends the flow - response is the question itself
    # (user's reply starts a new flow run with conversation context)
    
    # All actions lead to Confirm
    schedule_once - "confirm" >> confirm
    schedule_cron - "confirm" >> confirm
    schedule_cron_finite - "confirm" >> confirm
    list_reminders - "confirm" >> confirm
    cancel_reminder - "confirm" >> confirm
    cancel_all_reminders - "confirm" >> confirm
    edit_reminder - "confirm" >> confirm
    edit_reminder - "decide_action" >> decide_action
    set_timezone - "confirm" >> confirm
    
    return Flow(start=parse_input)


if __name__ == "__main__":
    # Test the flow with mock input
    flow = create_reminder_flow()
    
    shared = {
        "user_id": "test_user",
        "chat_id": "test_chat",
        "message": "Remind me to call mom tomorrow at 3pm"
    }
    
    flow.run(shared)
    
    print("\n--- Final shared state ---")
    print(f"Response: {shared.get('response')}")
    print(f"Needs reply: {shared.get('needs_reply')}")
    print(f"Reminder: {shared.get('reminder')}")
