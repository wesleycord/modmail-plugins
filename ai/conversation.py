import mimetypes
import re
from pathlib import PurePath


MAX_MESSAGES = 100
MAX_CONTEXT_CHARS = 12000
MAX_MESSAGE_CHARS = 4000
MAX_HISTORY_MESSAGE_CHARS = 2000
DISCORD_ID_PATTERN = re.compile(r"(?<!\d)\d{15,25}(?!\d)")
CONTEXT_INSTRUCTIONS = (
    "CONVERSATION CONTEXT\n"
    "The transcript below is chronological and contains User, AI, and Staff "
    "messages. User opened the thread, AI is the automated assistant, and Staff "
    "are moderators responding in the server.\n\n"
    "Use earlier messages to determine the ongoing task, not just the latest words. "
    "Carry forward the user's goal, facts, identifiers, evidence, decisions, and "
    "questions that still need answers. A short message such as an ID, username, "
    "yes, no, or an attachment is usually a continuation of the previous request.\n"
    "Before asking anything, search the transcript and current message for the "
    "answer. Never repeat a question that was already answered. Treat AI messages "
    "as prior attempts that may be incomplete or wrong, and treat Staff messages "
    "as support-team context.\n"
    "The newest user message appears separately after this transcript. Respond to "
    "the ongoing task based on all relevant messages, not to the newest words alone.\n\n"
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


def _author_details(message):
    author = message.get("author") or {}
    if isinstance(author, dict):
        name = author.get("name")
        author_id = author.get("id")
    else:
        name = str(author)
        author_id = None

    name = name or message.get("author_name") or "User"
    author_id = (
        author_id
        or message.get("author_id")
        or message.get("user_id")
        or message.get("recipient_id")
    )
    return str(name), str(author_id) if author_id is not None else None


def _message_kind(message):
    author = message.get("author") or {}
    author_data = author if isinstance(author, dict) else {}

    if (
        message.get("ai")
        or message.get("bot")
        or author_data.get("ai")
        or author_data.get("bot")
    ):
        return "AI"
    if message.get("mod") or author_data.get("mod"):
        return "Staff"
    return "User"


def _format_message(message, kind):
    name, author_id = _author_details(message)
    content = str(message.get("content") or "")[:MAX_HISTORY_MESSAGE_CHARS]
    attachments = _attachment_summary(message.get("attachments"))
    if not content and not attachments:
        return None

    speaker = kind
    identity = f"name={name}"
    if author_id:
        identity += f", user_id={author_id}"
    formatted = f"{speaker} [{identity}]: {content or '[no text]'}"
    if attachments:
        formatted += f" [Attachments: {', '.join(attachments)}]"
    return formatted


def _format_context(history):
    entries = "\n".join(
        f"{index}. {entry}" for index, entry in enumerate(history, start=1)
    )
    return CONTEXT_INSTRUCTIONS + entries


def build(log, current_message, include_ai_context=True):
    """Build context separately from the only message that needs an answer."""
    messages = log.get("messages", []) or []
    current_message_id = str(current_message.id)
    history = []
    history_chars = 0

    for message in messages:
        if not isinstance(message, dict):
            continue

        if str(message.get("message_id")) == current_message_id:
            continue

        kind = _message_kind(message)
        if kind is None:
            continue
        if kind == "AI" and not include_ai_context:
            continue

        formatted = _format_message(message, kind)
        if formatted is None:
            continue

        history.append(formatted)
        history_chars += len(history[-1])

        if len(history) > MAX_MESSAGES:
            remove_index = 0
            history_chars -= len(history.pop(remove_index))

    current_content = str(current_message.content or "")[:MAX_MESSAGE_CHARS]
    current_attachments = _attachment_summary(current_message.attachments)
    if current_attachments:
        current_content += f" [Attachments: {', '.join(current_attachments)}]"
    current_author = current_message.author
    current_identity = (
        f"name={current_author.name}, user_id={current_author.id}"
    )
    current_details = (
        "KNOWN THREAD USER\n"
        f"username: {current_author.name}\n"
        f"user_id: {current_author.id}\n\n"
    )
    current_content_ids = DISCORD_ID_PATTERN.findall(current_content)
    if current_content_ids:
        current_details += (
            "POSSIBLE USER IDs IN CURRENT MESSAGE\n"
            f"user_id candidates: {', '.join(current_content_ids)}\n\n"
        )
    context_item = {
        "role": "developer",
        "content": _format_context(history),
    }
    current_item = {
        "role": "user",
        "content": (
            "CURRENT USER MESSAGE - answer only this message. It is the newest entry "
            "after the chronological context above. The known details block is "
            "authoritative. Do not ask again for any username or ID found in the "
            "context or current message. Only ask for a reported user’s details if "
            "that reported user is different from the thread user and no details "
            "for that person were provided.\n\n"
            f"{current_details}"
            f"User ({current_identity}): "
            f"{current_content}"
        ),
    }

    while history and history_chars > MAX_CONTEXT_CHARS:
        remove_index = 0
        history_chars -= len(history.pop(remove_index))
        context_item["content"] = _format_context(history)

    return [context_item, current_item] if history else [current_item]