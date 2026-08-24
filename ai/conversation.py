import mimetypes
from pathlib import PurePath


MAX_MESSAGES = 200
MAX_CONTEXT_CHARS = 24000
MAX_MESSAGE_CHARS = 4000
CONTEXT_INSTRUCTIONS = (
    "CONVERSATION CONTEXT\n"
    "The entries below are in chronological order. They are background for "
    "the current user message, not separate requests to answer.\n"
    "- Original user request: the first user request in this thread.\n"
    "- User: a later message from the user.\n"
    "- AI assistant: a previous AI response, included for continuity only.\n"
    "Use all available entries to understand the current request. Treat details "
    "already provided, including usernames, user IDs, message IDs, and evidence, "
    "as known facts. Do not ask for a detail again when it is already present.\n"
    "Answer only the newest message shown after this context.\n\n"
)


def _attachment_summary(attachments):
    summaries = []
    for attachment in attachments or []:
        if isinstance(attachment, dict):
            name = attachment.get("filename") or attachment.get("name")
            file_type = attachment.get("content_type") or attachment.get("type")
        else:
            name = getattr(attachment, "filename", None) or getattr(
                attachment, "name", None
            )
            file_type = getattr(attachment, "content_type", None) or getattr(
                attachment, "type", None
            )

        if not name:
            name = "unnamed attachment"
        if not file_type:
            file_type = mimetypes.guess_type(str(name))[0] or PurePath(
                str(name)
            ).suffix.lstrip(".") or "unknown file type"

        summaries.append(f"{name} ({file_type})")

    return summaries


def _message_kind(message):
    author = message.get("author") or {}
    if not isinstance(author, dict):
        return None

    if message.get("mod") or author.get("mod"):
        return None
    if (
        message.get("ai")
        or message.get("bot")
        or author.get("ai")
        or author.get("bot")
    ):
        return "AI"
    return "User"


def _format_message(message, kind, is_original=False):
    author = message.get("author") or {}
    name = author.get("name") or "User"
    content = str(message.get("content") or "")[:MAX_MESSAGE_CHARS]
    attachments = _attachment_summary(message.get("attachments"))
    if not content and not attachments:
        return None

    if kind == "AI":
        speaker = "AI assistant"
    elif is_original:
        speaker = "Original user request"
    else:
        speaker = "User"
    formatted = f"{speaker} ({name}): {content}"
    if attachments:
        formatted += f" [Attachments: {', '.join(attachments)}]"
    return formatted


def _format_context(history):
    entries = "\n".join(
        f"{index}. {entry}" for index, entry in enumerate(history, start=1)
    )
    return CONTEXT_INSTRUCTIONS + entries


def build(log, current_message):
    """Build context separately from the only message that needs an answer."""
    messages = log.get("messages", []) or []
    current_message_id = str(current_message.id)
    history = []
    history_chars = 0
    original_request_found = False

    for message in messages:
        if not isinstance(message, dict):
            continue

        if str(message.get("message_id")) == current_message_id:
            continue

        kind = _message_kind(message)
        if kind is None:
            continue

        is_original = kind == "User" and not original_request_found
        formatted = _format_message(message, kind, is_original)
        if formatted is None:
            continue

        if is_original:
            original_request_found = True
        history.append(formatted)
        history_chars += len(history[-1])

        if len(history) > MAX_MESSAGES:
            remove_index = 1 if original_request_found else 0
            history_chars -= len(history.pop(remove_index))

    current_content = str(current_message.content or "")[:MAX_MESSAGE_CHARS]
    current_attachments = _attachment_summary(current_message.attachments)
    if current_attachments:
        current_content += f" [Attachments: {', '.join(current_attachments)}]"
    context_item = {
        "role": "developer",
        "content": _format_context(history),
    }
    current_item = {
        "role": "user",
        "content": (
            "CURRENT USER MESSAGE - answer only this message. It is the newest entry "
            "after the chronological context above. Do not re-request details the "
            "user already provided:\n"
            f"User ({current_message.author.name}): "
            f"{current_content}"
        ),
    }

    while history and history_chars > MAX_CONTEXT_CHARS:
        remove_index = 1 if original_request_found else 0
        history_chars -= len(history.pop(remove_index))
        context_item["content"] = _format_context(history)

    return [context_item, current_item] if history else [current_item]