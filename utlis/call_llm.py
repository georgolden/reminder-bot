from openai import OpenAI
from openai.types.chat.chat_completion_message import ChatCompletionMessage
import os
# Do NOT load .env here.

def call_llm(messages: list[dict]) -> str:
    """Simple LLM call (no tools)."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY environment variable not set.")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=60.0)

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        temperature=0.3,
    )

    return response.choices[0].message.content


def call_llm_with_tools(messages: list[dict], tools: list[dict]) -> ChatCompletionMessage:
    """LLM call with tool schema; returns message object with tool_calls."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY environment variable not set.")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=60.0)

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        tools=tools,
        tool_choice="auto",
        temperature=0.3,
    )

    return response.choices[0].message
