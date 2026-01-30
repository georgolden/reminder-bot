"""
Telegram bot entry point for the reminder agent.

NOTE: This repo does NOT load .env files automatically.
Set environment variables externally (or use your own tooling locally).
"""
import os

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from flow import create_reminder_flow
from utils import (
    init_scheduler,
    schedule_once,
    schedule_cron,
    get_all_reminders,
)

# Global flow instance
reminder_flow = create_reminder_flow()

# Store for conversation state (user_id -> conversation history)
conversations: dict[str, list[dict]] = {}


async def send_reminder(chat_id: str, text: str, reminder_id: str, app: Application, schedule_type: str = "once"):
    """Callback function for scheduled reminders."""
    message = f"🔔 {text}"
    try:
        await app.bot.send_message(chat_id=int(chat_id), text=message)
        print(f"[Reminder] Sent reminder {reminder_id} to chat {chat_id}")
    except Exception as e:
        print(f"[Reminder] Failed to send reminder {reminder_id} to chat {chat_id}: {e}")
        return

    # Auto-delete one-time reminders after firing
    if schedule_type == "once":
        from utils import delete_reminder

        delete_reminder(reminder_id)
        print(f"[Reminder] Auto-deleted one-time reminder {reminder_id}")


def _schedule_reminder_job(r: dict, app: Application):
    """Schedule a single reminder job."""
    callback_kwargs = {
        "chat_id": r["chat_id"],
        "text": r["text"],
        "reminder_id": r["id"],
        "app": app,
        "schedule_type": r["schedule_type"],
    }

    if r["schedule_type"] == "once":
        schedule_once(
            job_id=r["id"],
            run_date=r["schedule_value"],
            callback=send_reminder,
            timezone=r["timezone"],
            **callback_kwargs,
        )
    elif r["schedule_type"] == "cron":
        cron_expr = r.get("_cron_expression", r["schedule_value"])
        end_date = r.get("_end_date")

        if "|ends:" in r["schedule_value"]:
            cron_expr, end_str = r["schedule_value"].split("|ends:")
            end_date = end_str

        schedule_cron(
            job_id=r["id"],
            cron_expression=cron_expr,
            callback=send_reminder,
            timezone=r["timezone"],
            end_date=end_date,
            **callback_kwargs,
        )


def restore_scheduled_jobs(app: Application):
    """Restore scheduled jobs from storage on startup."""
    reminders = get_all_reminders()
    print(f"[Startup] Restoring {len(reminders)} reminders...")

    for r in reminders:
        try:
            _schedule_reminder_job(r, app)
            print(f"[Startup] Restored reminder: {r['id']}")
        except Exception as e:
            print(f"[Startup] Failed to restore reminder {r['id']}: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages."""
    user_id = str(update.effective_user.id)
    chat_id = str(update.effective_chat.id)
    message = update.message.text

    print(f"\n[Bot] Message from {user_id}: {message}")

    conversation = conversations.get(user_id, [])

    shared = {
        "user_id": user_id,
        "chat_id": chat_id,
        "message": message,
        "conversation": conversation.copy(),
    }

    try:
        reminder_flow.run(shared)

        # Schedule jobs requested by the flow
        if shared.get("schedule_job") and shared.get("reminder"):
            _schedule_reminder_job(shared["reminder"], context.application)

        if shared.get("schedule_jobs"):
            for r in shared["schedule_jobs"]:
                _schedule_reminder_job(r, context.application)

        response = shared.get("response", "Something went wrong.")
        await update.message.reply_text(response)

        if shared.get("needs_reply"):
            conversation.append({"role": "user", "content": message})
            conversation.append({"role": "assistant", "content": f"[Asked: {response}]"})
            conversations[user_id] = conversation
        else:
            conversations.pop(user_id, None)

    except Exception as e:
        print(f"[Bot] Error: {e}")
        import traceback

        traceback.print_exc()
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = """👋 Hi! I'm your reminder assistant.

I can help you:
• Schedule one-time reminders
• Set up recurring reminders
• List your active reminders
• Cancel reminders

Just tell me what you want to be reminded about!
"""
    await update.message.reply_text(welcome)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """📖 How to use:

One-time reminders:
- "Remind me to [task] at [time]"

Recurring reminders:
- "Remind me to [task] every day at [time]"

Manage reminders:
- "Show my reminders"
- "Cancel reminder [ID]"
"""
    await update.message.reply_text(help_text)


async def post_init(app: Application):
    init_scheduler()
    restore_scheduled_jobs(app)
    print("[Bot] Ready!")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

    print("[Bot] Starting...", flush=True)

    app = Application.builder().token(token).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("[Bot] Starting polling...", flush=True)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
