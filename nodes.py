"""
PocketFlow nodes for the reminder agent.
"""
import json
import re
from datetime import datetime
from typing import Any
from pocketflow import Node
import pytz

from utlis.call_llm import call_llm_with_tools
from tools import TOOLS
from utils import (
    schedule_once,
    schedule_cron,
    remove_job,
    save_reminder,
    get_reminders,
    delete_reminder,
    get_reminder,
    get_reminder_for_user,
    get_user_timezone,
    set_user_timezone
)




def _validate_timezone(tz: str) -> str | None:
    """Return error message if timezone is invalid, otherwise None."""
    try:
        pytz.timezone(tz)
        return None
    except Exception:
        return f"Invalid timezone: {tz}"


def _parse_iso_datetime(dt_str: str) -> tuple[datetime | None, str | None]:
    """Parse ISO datetime. Returns (datetime, error)."""
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return dt, None
    except Exception:
        return None, f"Invalid datetime: {dt_str}"


def _validate_cron_expression(expr: str) -> str | None:
    """Basic cron validation (5 fields, allowed characters)."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return f"Invalid cron expression: expected 5 fields, got {len(parts)}"
    for part in parts:
        if not re.match(r'^[\d\*/\-,]+$', part):
            return f"Invalid cron expression part: {part}"
    return None


SYSTEM_PROMPT = """You are a reminder assistant. Your job is to help users schedule reminders.

Current date and time: {current_datetime}
User's timezone: {user_timezone}

INSTRUCTIONS:
1. Analyze the user's request to understand what they want to be reminded about and when.
2. **SCHEDULE IMMEDIATELY if you have enough info** - don't ask unnecessary questions!
3. For one-time reminders, use schedule_once with an ISO datetime and timezone.
4. Use schedule_cron only when a recurrence is explicitly specified.
5. If recurrence is NOT specified, always use schedule_cron_finite with end_datetime_iso + timezone.
6. If user wants to see their reminders, use list_reminders.
7. If user wants to cancel a reminder, use cancel_reminder with the reminder ID.
8. If user wants to cancel all reminders, use cancel_all_reminders.
9. If user wants to change/update an existing reminder, use edit_reminder with reminder_id + reminder_name + new_reminder_name + new_query. If no new name is provided, use the old name as new_reminder_name. new_query must include the reminder name and schedule.
10. If user wants to set timezone explicitly, use set_timezone (otherwise always use stored timezone).

SMART DEFAULTS (DON'T ASK - JUST USE):
- "immediately" / "now" / "right now" → use current time + 1 minute
- "every minute" → cron: "* * * * *"
- "every hour" → cron: "0 * * * *"
- "every day at X" → cron with that hour
- "tomorrow" → next day at the specified time (or 9:00 AM if no time given)
- No timezone specified → use user's timezone ({user_timezone})
- For finite recurring schedules, use schedule_cron_finite with end_datetime_iso.
- If user specifies a time WINDOW with interval (e.g., "from 01:00 to 01:30 every 5 minutes") and does NOT specify recurrence, always use schedule_cron_finite. end_datetime_iso = window end today unless a different end date is specified.

PARAMETERS TO EXTRACT (WHEN PRESENT):
- reminder_text
- interval_minutes (e.g., every 5 minutes)
- window_start_time (e.g., 00:40)
- window_end_time (e.g., 01:40)
- recurrence (daily / weekly / weekdays / specific days)
- start_date (if specified)
- end_date (if specified) OR duration_days (e.g., "for 2 days")
- timezone (always from stored user data, not user input)

CONVERTING TO CRON:
- interval_minutes → minute field ("*/N")
- window time range → hour field ("H1-H2")
- recurrence:
  - daily → day/month/dow = "*"
  - weekdays → dow = "1-5"
  - specific days → dow list (e.g., "1,3,5")
- Use schedule_cron_finite when a finite end is required (end_datetime_iso).
- If a window end is specified and no other end date is given, use the window end as the end_datetime_iso for that day.

TIME WINDOWS / INTERVALS (IMPORTANT):
If user specifies a recurring *window* like "from 00:40 to 01:40 every 5 minutes":
- Use cron to target BOTH minute interval and hour range.
- Example: "every 5 minutes from 00:40 to 01:40 daily" → cron "*/5 0-1 * * *"
- Example: "from 02:05 to 02:20 every 1 minute for 2 days" → cron "*/1 2 * * *" with end_datetime_iso at day+2 02:20.
- Example: "from 01:00 to 01:30 every 1 minute today" → schedule_cron_finite with end_datetime_iso at 01:30 today.
- If a START time is given, use that start time even if it is in the past (do not shift to next day unless user asks).
- If user says "start immediately", schedule should run from now until end of window today, then resume in next window(s) if a multi-day duration is given.
- The window end time is the end of EACH daily window.
- If recurrence is NOT specified, the window end time is also the overall end for today.

END DATE / DURATION FOR WINDOWS:
- "for 2 days" → compute end_datetime_iso = start_date + 2 days at the WINDOW END time.
- Use schedule_cron_finite with end_datetime_iso (total schedule length across days).
- The window end time is the end of each daily window; for non-recurring windows it is also the overall end.
- Do NOT set end_datetime_iso to the current time or the next minute.
- If window end (e.g., 01:40) is not aligned with the interval, include the reminder at the end time.

CRON EXPRESSION FORMAT (5 fields):
- minute (0-59)
- hour (0-23)  
- day of month (1-31)
- month (1-12)
- day of week (0-6, 0=Sunday)

Examples:
- "* * * * *" = every minute
- "0 9 * * *" = every day at 9:00 AM
- "30 14 * * 1-5" = weekdays at 2:30 PM
- "*/5 * * * *" = every 5 minutes

EDITING REMINDERS:
Use edit_reminder for ANY modification to an existing reminder:
- "move to X" / "reschedule to X" / "reset to X" / "change to X"
- "make it X instead" / "shift to X" / "update to X"
- If user mentions the reminder NAME/TEXT and does NOT say cancel/delete, treat it as an edit request.
- Provide reminder_id + reminder_name + new_reminder_name + new_query (new_query must include all details needed to schedule the new reminder).
- edit_reminder cancels old reminder and re-runs scheduling.

RESOLVING "WHICH REMINDER":
Look at USER'S ACTIVE REMINDERS below to find the ID:
- If user mentions reminder TEXT/NAME, match by text (case-insensitive).
- "the reminder" / "it" / "this" / "that" → the one from context or conversation
- "current" / "my reminder" → if ONE exists, that's it
- "last" / "just set" → most recent by created_at
- Single reminder + vague reference → assume that one, don't ask

CANCEL SHORTCUTS:
- "cancel/delete/stop it" + one reminder → cancel that one
- "cancel all" → cancel_all_reminders
- Never ask "which one" if only one exists

ONLY ASK QUESTIONS WHEN:
- You genuinely cannot determine WHAT to remind about
- The time is completely ambiguous (e.g., "remind me later" with no context)

DO NOT ASK ABOUT:
- Timezone (use default: {user_timezone})
- "When should it start?" if user said "immediately" or "now"
- Confirmation of details you can reasonably infer
- Which reminder to cancel if user just says "cancel" without ID - use cancel_all

You MUST call a tool - never respond without using a tool.
"""


class ParseInput(Node):
    """Initialize shared store from incoming message."""
    
    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id": shared.get("user_id"),
            "chat_id": shared.get("chat_id"),
            "message": shared.get("message"),
            "conversation": shared.get("conversation", [])
        }
    
    def exec(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return inputs
    
    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: dict[str, Any]) -> str:
        shared["original_message"] = exec_res["message"]
        # Preserve existing conversation, don't reset it!
        if "conversation" not in shared or not shared["conversation"]:
            shared["conversation"] = exec_res.get("conversation", [])
        print(f"[ParseInput] User {exec_res['user_id']}: {exec_res['message']} (conversation: {len(shared['conversation'])} msgs)")
        return "default"


class DecideAction(Node):
    """LLM decides what action to take."""
    
    def __init__(self):
        super().__init__(max_retries=3, wait=1)
    
    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        # Get user's active reminders for context
        user_reminders = get_reminders(shared["user_id"])
        
        return {
            "original_message": shared["original_message"],
            "conversation": shared.get("conversation", []),
            "user_id": shared["user_id"],
            "user_reminders": user_reminders
        }
    
    def _format_reminder_for_context(self, r: dict) -> str:
        """Format a reminder for context display."""
        if r['schedule_type'] == 'cron':
            cron_expr = r['schedule_value']
            if "|ends:" in cron_expr:
                cron_expr = cron_expr.split("|ends:")[0]
            return f"- [{r['id']}] \"{r['text']}\" (recurring: {cron_expr})"
        else:
            return f"- [{r['id']}] \"{r['text']}\" (at {r['schedule_value']})"
    
    def exec(self, inputs: dict[str, Any]) -> Any:
        # Get user's timezone
        user_tz = get_user_timezone(inputs["user_id"])
        
        # Build messages with user's timezone
        import pytz
        from datetime import timezone as dt_timezone
        try:
            tz = pytz.timezone(user_tz)
            current_dt = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
        except:
            current_dt = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Build user's reminders context
        user_reminders = inputs.get("user_reminders", [])
        if user_reminders:
            reminders_context = "\n\nUSER'S ACTIVE REMINDERS:\n" + "\n".join(
                self._format_reminder_for_context(r) for r in user_reminders
            )
        else:
            reminders_context = "\n\nUSER'S ACTIVE REMINDERS: None"
        
        system_prompt = SYSTEM_PROMPT.format(
            current_datetime=current_dt,
            user_timezone=user_tz
        ) + reminders_context
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history (last 4 messages max to avoid pollution)
        conversation = inputs["conversation"][-4:] if inputs["conversation"] else []
        for msg in conversation:
            messages.append(msg)
        
        # Always add the current message
        messages.append({
            "role": "user",
            "content": inputs["original_message"]
        })
        
        print(f"[DecideAction] Calling LLM with {len(messages)} messages (user_tz: {user_tz})")
        print(f"[DecideAction] Context: {len(conversation)} conv msgs, {len(user_reminders)} reminders")
        
        # Call LLM with tools
        response = call_llm_with_tools(messages, TOOLS)
        
        if not response.tool_calls:
            raise Exception("LLM did not call any tool!")
        
        # Return first tool call (DeepSeek doesn't support parallel)
        return response.tool_calls[0]
    
    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: Any) -> str:
        # Handle single tool call
        tool_calls = exec_res if isinstance(exec_res, list) else [exec_res]
        
        # Take first tool call (DeepSeek doesn't support parallel)
        tc = tool_calls[0]
        tool_name = tc.function.name
        tool_args = json.loads(tc.function.arguments)
        
        print(f"[DecideAction] Tool: {tool_name}, Args: {tool_args}")
        
        shared["tool_name"] = tool_name
        shared["tool_args"] = tool_args
        
        # Route based on tool
        if tool_name == "ask_user":
            shared["question"] = tool_args["question"]
            return "need_info"
        elif tool_name == "schedule_once":
            return "schedule_once"
        elif tool_name == "schedule_cron":
            return "schedule_cron"
        elif tool_name == "schedule_cron_finite":
            return "schedule_cron_finite"
        elif tool_name == "list_reminders":
            return "list"
        elif tool_name == "cancel_reminder":
            return "cancel"
        elif tool_name == "cancel_all_reminders":
            return "cancel_all"
        elif tool_name == "set_timezone":
            return "set_timezone"
        elif tool_name == "edit_reminder":
            return "edit"
        else:
            raise Exception(f"Unknown tool: {tool_name}")


class AskUser(Node):
    """Request missing information from user."""
    
    def prep(self, shared: dict[str, Any]) -> str:
        return shared["question"]
    
    def exec(self, question: str) -> str:
        print(f"[AskUser] Question: {question}")
        return question
    
    def post(self, shared: dict[str, Any], prep_res: str, exec_res: str) -> str:
        # Store question as response (bot will send this)
        shared["response"] = f"❓ {exec_res}"
        shared["needs_reply"] = True
        print(f"[AskUser] Response set: {shared['response'][:100]}...")
        return "done"  # End flow here, response is the question


class ScheduleOnce(Node):
    """Create one-time reminder."""
    
    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        args = shared["tool_args"]
        return {
            "user_id": shared["user_id"],
            "chat_id": shared["chat_id"],
            "reminder_text": args["reminder_text"],
            "datetime_iso": args["datetime_iso"],
            "timezone": args["timezone"]
        }
    
    def exec(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from utils.storage import generate_reminder_id
        
        # Validate timezone
        tz_error = _validate_timezone(inputs["timezone"])
        if tz_error:
            return {"error": tz_error}
        
        # Validate datetime
        _, dt_error = _parse_iso_datetime(inputs["datetime_iso"])
        if dt_error:
            return {"error": dt_error}
        
        reminder_id = generate_reminder_id()
        
        # Save to storage
        reminder = save_reminder(
            user_id=inputs["user_id"],
            chat_id=inputs["chat_id"],
            text=inputs["reminder_text"],
            schedule_type="once",
            schedule_value=inputs["datetime_iso"],
            timezone=inputs["timezone"],
            reminder_id=reminder_id
        )
        
        return reminder
    
    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        if exec_res.get("error"):
            shared["response"] = f"⚠️ {exec_res['error']}"
            shared["needs_reply"] = False
            return "done"
        shared["reminder"] = exec_res
        shared["schedule_job"] = True  # Flag for main.py to schedule the actual job
        print(f"[ScheduleOnce] Created reminder: {exec_res['id']}")
        return "confirm"


class ScheduleCronFinite(Node):
    """Create recurring reminder with cron expression and a required end datetime."""
    
    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        args = shared["tool_args"]
        return {
            "user_id": shared["user_id"],
            "chat_id": shared["chat_id"],
            "reminder_text": args["reminder_text"],
            "cron_expression": args["cron_expression"],
            "end_datetime_iso": args["end_datetime_iso"],
            "timezone": args["timezone"]
        }
    
    def exec(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from utils.storage import generate_reminder_id
        
        # Validate timezone
        tz_error = _validate_timezone(inputs["timezone"])
        if tz_error:
            return {"error": tz_error}
        
        # Validate cron
        cron_error = _validate_cron_expression(inputs["cron_expression"])
        if cron_error:
            return {"error": cron_error}
        
        # Validate end datetime
        _, end_error = _parse_iso_datetime(inputs["end_datetime_iso"])
        if end_error:
            return {"error": end_error}
        
        reminder_id = generate_reminder_id()
        
        schedule_value = f"{inputs['cron_expression']}|ends:{inputs['end_datetime_iso']}"
        
        reminder = save_reminder(
            user_id=inputs["user_id"],
            chat_id=inputs["chat_id"],
            text=inputs["reminder_text"],
            schedule_type="cron",
            schedule_value=schedule_value,
            timezone=inputs["timezone"],
            reminder_id=reminder_id
        )
        
        reminder["_end_date"] = inputs["end_datetime_iso"]
        reminder["_cron_expression"] = inputs["cron_expression"]
        
        return reminder
    
    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        if exec_res.get("error"):
            shared["original_message"] = (
                f"Error: {exec_res['error']}. "
                "Recompute end_datetime_iso correctly (end of window on end day). "
                f"Original request: {shared.get('original_message','')}"
            )
            return "decide_action"
        shared["reminder"] = exec_res
        shared["schedule_job"] = True
        print(f"[ScheduleCronFinite] Created reminder: {exec_res['id']}")
        return "confirm"


class ScheduleCron(Node):
    """Create recurring reminder with cron expression."""
    
    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        args = shared["tool_args"]
        user_tz = get_user_timezone(shared["user_id"])
        return {
            "user_id": shared["user_id"],
            "chat_id": shared["chat_id"],
            "reminder_text": args["reminder_text"],
            "cron_expression": args["cron_expression"],
            "timezone": args["timezone"]
        }
    
    def exec(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from utils.storage import generate_reminder_id
        # Validate timezone
        tz_error = _validate_timezone(inputs["timezone"])
        if tz_error:
            return {"error": tz_error}
        
        # Validate cron
        cron_error = _validate_cron_expression(inputs["cron_expression"])
        if cron_error:
            return {"error": cron_error}
        
        reminder_id = generate_reminder_id()
        
        # Save to storage
        schedule_value = inputs["cron_expression"]
        
        reminder = save_reminder(
            user_id=inputs["user_id"],
            chat_id=inputs["chat_id"],
            text=inputs["reminder_text"],
            schedule_type="cron",
            schedule_value=schedule_value,
            timezone=inputs["timezone"],
            reminder_id=reminder_id
        )
        
        reminder["_end_date"] = None
        reminder["_cron_expression"] = inputs["cron_expression"]
        
        return reminder
    
    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        if exec_res.get("error"):
            shared["response"] = f"⚠️ {exec_res['error']}"
            shared["needs_reply"] = False
            return "done"
        shared["reminder"] = exec_res
        shared["schedule_job"] = True
        print(f"[ScheduleCron] Created reminder: {exec_res['id']}")
        return "confirm"


class ListReminders(Node):
    """List user's active reminders."""
    
    def prep(self, shared: dict[str, Any]) -> str:
        return shared["user_id"]
    
    def exec(self, user_id: str) -> list[dict]:
        reminders = get_reminders(user_id)
        print(f"[ListReminders] Found {len(reminders)} reminders for user {user_id}")
        return reminders
    
    def post(self, shared: dict[str, Any], prep_res: str, exec_res: list[dict]) -> str:
        shared["reminders_list"] = exec_res
        return "confirm"


class CancelReminder(Node):
    """Cancel a specific reminder."""
    
    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "reminder_id": shared["tool_args"]["reminder_id"],
            "user_id": shared["user_id"]
        }
    
    def exec(self, inputs: dict[str, Any]) -> dict[str, Any]:
        reminder_id = inputs["reminder_id"]
        user_id = inputs["user_id"]
        # Get reminder info before deleting
        reminder = get_reminder_for_user(reminder_id, user_id)
        
        if reminder is None:
            return {"success": False, "error": "Reminder not found"}
        
        # Remove from scheduler
        remove_job(reminder_id)
        
        # Mark as deleted in storage
        success = delete_reminder(reminder_id)
        
        return {
            "success": success,
            "reminder": reminder if success else None
        }
    
    def post(self, shared: dict[str, Any], prep_res: str, exec_res: dict[str, Any]) -> str:
        shared["cancel_result"] = exec_res
        print(f"[CancelReminder] Result: {exec_res}")
        return "confirm"


class EditReminder(Node):
    """Edit an existing reminder by ID, then re-run scheduling."""
    
    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        args = shared["tool_args"]
        return {
            "user_id": shared["user_id"],
            "chat_id": shared["chat_id"],
            "reminder_id": args["reminder_id"],
            "reminder_name": args["reminder_name"],
            "new_reminder_name": args["new_reminder_name"],
            "new_query": args["new_query"],
            "timezone": args["timezone"]
        }
    
    def exec(self, inputs: dict[str, Any]) -> dict[str, Any]:
        # Get reminder by ID and verify user
        reminder = get_reminder_for_user(inputs["reminder_id"], inputs["user_id"])
        if not reminder:
            return {"error": f"Reminder id '{inputs['reminder_id']}' not found"}
        
        # Optional name check (non-fatal): do not block, just log
        if reminder.get("text", "").lower() != inputs["reminder_name"].lower():
            print(f"[EditReminder] Name mismatch: '{reminder.get('text','')}' vs '{inputs['reminder_name']}'")
        
        # Cancel old reminder
        remove_job(reminder["id"])
        delete_reminder(reminder["id"])
        
        # Ensure new_query contains new reminder name
        if inputs["new_reminder_name"].lower() not in inputs["new_query"].lower():
            inputs["new_query"] = f"{inputs['new_reminder_name']}: {inputs['new_query']}"
        
        return {"next_query": inputs["new_query"]}
    
    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        if exec_res.get("error"):
            shared["response"] = f"⚠️ {exec_res['error']}"
            shared["needs_reply"] = False
            return "done"
        
        # Replace original message with the new query and loop back to DecideAction
        shared["original_message"] = exec_res["next_query"]
        return "decide_action"


class CancelAllReminders(Node):
    """Cancel all reminders for a user."""
    
    def prep(self, shared: dict[str, Any]) -> str:
        return shared["user_id"]
    
    def exec(self, user_id: str) -> dict[str, Any]:
        reminders = get_reminders(user_id)
        cancelled = []
        
        for r in reminders:
            remove_job(r["id"])
            delete_reminder(r["id"])
            cancelled.append(r)
        
        return {
            "count": len(cancelled),
            "cancelled": cancelled
        }
    
    def post(self, shared: dict[str, Any], prep_res: str, exec_res: dict[str, Any]) -> str:
        shared["cancel_all_result"] = exec_res
        print(f"[CancelAllReminders] Cancelled {exec_res['count']} reminders")
        return "confirm"

class SetTimezone(Node):
    """Set user's preferred timezone."""
    
    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id": shared["user_id"],
            "timezone": shared["tool_args"]["timezone"]
        }
    
    def exec(self, inputs: dict[str, Any]) -> dict[str, Any]:
        import pytz
        tz_str = inputs["timezone"]
        
        # Validate timezone
        try:
            pytz.timezone(tz_str)
        except pytz.exceptions.UnknownTimeZoneError:
            return {"success": False, "error": f"Unknown timezone: {tz_str}"}
        
        set_user_timezone(inputs["user_id"], tz_str)
        return {"success": True, "timezone": tz_str}
    
    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        shared["timezone_result"] = exec_res
        print(f"[SetTimezone] Result: {exec_res}")
        return "confirm"


class Confirm(Node):
    """Generate confirmation message."""
    
    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool_name": shared.get("tool_name"),
            "reminder": shared.get("reminder"),
            "reminders_list": shared.get("reminders_list"),
            "cancel_result": shared.get("cancel_result"),
            "cancel_all_result": shared.get("cancel_all_result"),
            "timezone_result": shared.get("timezone_result"),
            "edit_result": shared.get("edit_result"),
            "batch_results": shared.get("batch_results"),
            "user_id": shared.get("user_id")
        }
    
    def _format_datetime(self, dt_str: str, stored_tz: str, user_id: str = None) -> str:
        """Format datetime string in user's timezone."""
        import pytz
        try:
            # Parse ISO datetime
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            
            # If naive, assume it's in the stored timezone
            if dt.tzinfo is None:
                stored_tz_obj = pytz.timezone(stored_tz)
                dt = stored_tz_obj.localize(dt)
            
            # Convert to user's timezone for display
            if user_id:
                user_tz_str = get_user_timezone(user_id)
                user_tz = pytz.timezone(user_tz_str)
                dt = dt.astimezone(user_tz)
            
            # Format nicely
            return dt.strftime("%b %d at %H:%M")
        except:
            return dt_str
    
    def _describe_cron(self, cron_expr: str) -> str:
        """Convert cron to human-readable description."""
        # Handle end_date suffix
        end_info = ""
        if "|ends:" in cron_expr:
            cron_expr, end_str = cron_expr.split("|ends:")
            try:
                end_dt = datetime.fromisoformat(end_str)
                end_info = f" (until {end_dt.strftime('%H:%M')})"
            except:
                pass
        
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return cron_expr + end_info
        
        minute, hour, day, month, dow = parts
        
        desc = cron_expr
        if cron_expr.strip() == "* * * * *":
            desc = "every minute"
        elif minute == "0" and hour == "*":
            desc = "every hour"
        elif minute != "*" and hour != "*" and day == "*" and month == "*" and dow == "*":
            desc = f"daily at {hour.zfill(2)}:{minute.zfill(2)}"
        elif minute.startswith("*/"):
            desc = f"every {minute[2:]} minutes"
        elif hour.startswith("*/"):
            desc = f"every {hour[2:]} hours"
        
        return desc + end_info
    
    def exec(self, inputs: dict[str, Any]) -> str:
        tool_name = inputs["tool_name"]
        
        if tool_name == "schedule_once":
            r = inputs["reminder"]
            formatted_time = self._format_datetime(r['schedule_value'], r['timezone'], inputs.get('user_id'))
            return f"✅ Reminder set!\n\n📝 {r['text']}\n⏰ {formatted_time}"
        
        elif tool_name == "schedule_cron":
            r = inputs["reminder"]
            cron_desc = self._describe_cron(r['schedule_value'])
            return f"✅ Recurring reminder set!\n\n📝 {r['text']}\n🔄 {cron_desc}"
        
        elif tool_name == "list_reminders":
            reminders = inputs["reminders_list"]
            if not reminders:
                return "📋 You have no active reminders."
            
            lines = ["📋 Your reminders:\n"]
            for r in reminders:
                if r['schedule_type'] == 'cron':
                    schedule_info = f"🔄 {self._describe_cron(r['schedule_value'])}"
                else:
                    schedule_info = f"📅 {self._format_datetime(r['schedule_value'], r['timezone'], inputs.get('user_id'))}"
                lines.append(f"• {r['text']}\n  {schedule_info}")
            
            return "\n".join(lines)
        
        elif tool_name == "cancel_reminder":
            result = inputs["cancel_result"]
            if result["success"]:
                r = result["reminder"]
                return f"❌ Reminder cancelled: {r['text']}"
            else:
                return f"⚠️ Could not cancel reminder: {result.get('error', 'Unknown error')}"
        
        elif tool_name == "cancel_all_reminders":
            result = inputs["cancel_all_result"]
            count = result["count"]
            if count == 0:
                return "📋 No reminders to cancel."
            return f"🗑️ Cancelled {count} reminder(s)!"
        
        elif tool_name == "set_timezone":
            result = inputs["timezone_result"]
            if result["success"]:
                return f"🌍 Timezone set to {result['timezone']}!"
            else:
                return f"⚠️ {result['error']}"
        
        elif tool_name == "edit_reminder":
            result = inputs["edit_result"]
            if result["success"]:
                old_r = result["old_reminder"]
                new_r = result["new_reminder"]
                new_time = self._format_datetime(new_r['schedule_value'], new_r['timezone'], inputs.get('user_id'))
                return f"✏️ Reminder updated!\n\n📝 {new_r['text']}\n⏰ {new_time}"
            else:
                return f"⚠️ {result['error']}"
        
        # Handle batch results (multiple tool calls)
        batch_results = inputs.get("batch_results")
        if batch_results:
            return self._format_batch_results(batch_results, inputs.get('user_id'))
        
        return "Done!"
    
    def _format_batch_results(self, results: list[dict], user_id: str = None) -> str:
        """Format results from multiple tool executions."""
        lines = []
        
        for result in results:
            if not result["success"]:
                lines.append(f"⚠️ {result['error']}")
                continue
                
            data = result["data"]
            if not data:
                continue
                
            result_type = data.get("type")
            
            if result_type == "scheduled":
                r = data["reminder"]
                formatted_time = self._format_datetime(r['schedule_value'], r['timezone'], user_id)
                lines.append(f"✅ Reminder set: {r['text']} ({formatted_time})")
                
            elif result_type == "scheduled_cron":
                r = data["reminder"]
                cron_desc = self._describe_cron(r['schedule_value'])
                lines.append(f"✅ Recurring: {r['text']} ({cron_desc})")
                
            elif result_type == "cancelled":
                r = data["reminder"]
                lines.append(f"❌ Cancelled: {r['text']}")
                
            elif result_type == "cancelled_all":
                count = data["count"]
                lines.append(f"🗑️ Cancelled {count} reminder(s)")
                
            elif result_type == "list":
                reminders = data["reminders"]
                if not reminders:
                    lines.append("📋 No active reminders")
                else:
                    lines.append("📋 Your reminders:")
                    for r in reminders:
                        if r['schedule_type'] == 'cron':
                            schedule_info = self._describe_cron(r['schedule_value'])
                        else:
                            schedule_info = self._format_datetime(r['schedule_value'], r['timezone'], user_id)
                        lines.append(f"  • {r['text']} ({schedule_info})")
                        
            elif result_type == "timezone_set":
                lines.append(f"🌍 Timezone: {data['timezone']}")
        
        return "\n".join(lines) if lines else "Done!"
    
    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: str) -> str:
        shared["response"] = exec_res
        shared["needs_reply"] = False
        print(f"[Confirm] Response: {exec_res[:100]}...")
        return "done"
