import asyncio
import json
import logging
from datetime import datetime, timezone
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import ValidationError

from app.ai.prompts import SYSTEM_PROMPT
from app.ai.sanitize import sanitize_chat_text
from app.ai.tools import build_tools
from app.core.errors import AppError
from app.services.common import as_utc, now_utc

logger = logging.getLogger(__name__)


async def chat(db, user, message: str, llm, obp, settings, tavily, request_id=None):
    user_id = str(user["_id"])
    safe_message = sanitize_chat_text(message)
    timestamp = now_utc()
    await db.chat_messages.insert_one({"user_id": user_id, "sender": "user", "text": safe_message, "timestamp": timestamp, "meta": {}})
    history = await db.chat_messages.find({"user_id": user_id}).sort("timestamp", -1).limit(13).to_list(13)
    history.reverse()
    # Current message is already in history. The model receives at most 12 prior user/bot turns.
    history = history[:-1][-12:]
    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    for item in history:
        if item.get("sender") == "user": messages.append(HumanMessage(content=sanitize_chat_text(item.get("text", ""))))
        elif item.get("sender") == "bot": messages.append(AIMessage(content=sanitize_chat_text(item.get("text", ""))))
    messages.append(HumanMessage(content=safe_message))
    tools = build_tools(db, obp, settings, tavily, user, safe_message)
    tool_map = {t.name: t for t in tools}
    tool_names = set()
    pending_action = None
    try:
        async with asyncio.timeout(50):
            for _ in range(5):
                answer = await llm.invoke(messages, tools)
                calls = getattr(answer, "tool_calls", None) or []
                messages.append(answer)
                if not calls:
                    reply = str(answer.content or "").strip()
                    if not reply: reply = "I couldn't form a helpful answer. Could you rephrase that?"
                    break
                for call in calls:
                    name = call.get("name")
                    tool_names.add(name)
                    call_id = call.get("id") or f"tool-{len(tool_names)}"
                    args = call.get("args")
                    if name not in tool_map or not isinstance(args, dict):
                        output = "Invalid tool call. Use only the available tool schema."
                    else:
                        try:
                            validated = tool_map[name].args_schema.model_validate(args)
                            result = await tool_map[name].ainvoke(validated.model_dump())
                            output = result if isinstance(result, str) else json.dumps(result, default=str)
                            if name == "prepare_payment" and isinstance(result, dict):
                                pending_action = {"type": "confirm_payment", **result}
                            await db.audit_log.insert_one({"user_id": user_id, "event": "ai_tool_called", "details": {"tool": name}, "request_id": request_id, "timestamp": now_utc()})
                        except (ValidationError, ValueError, TypeError):
                            output = "Invalid tool arguments. Please repair once or answer without the tool."
                    messages.append(ToolMessage(content=str(output)[:8000], tool_call_id=call_id))
            else:
                reply = "I couldn't complete that safely in one conversation. Please try a shorter request."
    except TimeoutError as exc:
        raise AppError("AI_UNAVAILABLE", "The assistant took too long to respond. Please try again.", 503) from exc
    except AppError:
        raise
    except Exception as exc:
        logger.warning("AI request failed error_type=%s", type(exc).__name__)
        raise AppError("AI_UNAVAILABLE", "The assistant is temporarily unavailable.", 503) from exc
    await db.chat_messages.insert_one({"user_id": user_id, "sender": "bot", "text": reply, "timestamp": now_utc(), "meta": {"tools": sorted(x for x in tool_names if x)}})
    prompts = []
    if "get_spending_summary" in tool_names: prompts = ["Show dining spend", "How does this compare with last month?", "Check my budget status"]
    elif "get_budget_status" in tool_names: prompts = ["Show my recent transactions", "Which budget is closest to its limit?", "Summarize this month's spending"]
    elif "prepare_payment" in tool_names: prompts = ["Review this payment", "Check my available balance", "Show recent transactions"]
    elif "get_transactions" in tool_names: prompts = ["Summarize this month's spending", "Check my budget status", "Show unread alerts"]
    else: prompts = ["How much did I spend this month?", "Check my budget status", "Show recent transactions"]
    return {"reply": reply, "suggestedPrompts": prompts[:3], "timestamp": now_utc().isoformat(), **({"pendingAction": pending_action} if pending_action else {})}


async def history(db, user_id: str, page: int = 1, limit: int = 50):
    total = await db.chat_messages.count_documents({"user_id": user_id})
    rows = await db.chat_messages.find({"user_id": user_id}).sort("timestamp", 1).skip((page - 1) * limit).limit(limit).to_list(limit)
    return {"messages": [{"id": str(row.get("_id")), "sender": row["sender"], "text": row["text"], "timestamp": as_utc(row["timestamp"]).isoformat()} for row in rows], "pagination": {"page": page, "limit": limit, "totalCount": total}}
