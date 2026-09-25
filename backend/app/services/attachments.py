import csv
import io
import json
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException
from sqlalchemy import select
from app.models import Attachment


def csv_statistics(text):
    rows = list(csv.reader(io.StringIO(text), strict=True))
    if not rows:
        return {}
    columns = {}
    for index, name in enumerate(rows[0]):
        numbers = []
        for row in rows[1:]:
            value = row[index].strip() if index < len(row) else ""
            if not value:
                continue
            try:
                number = Decimal(value)
                if not number.is_finite():
                    break
                numbers.append(number)
            except InvalidOperation:
                break
        else:
            if numbers:
                columns[f"{index + 1}: {name}"] = {
                    "count": len(numbers), "highest": str(max(numbers)), "lowest": str(min(numbers)),
                    "average": str(sum(numbers) / len(numbers)), "total": str(sum(numbers))}
    return columns


def attach_context(db, user_id, chat_id, prompt, attachment_ids):
    for attachment_id in attachment_ids:
        attachment = db.scalar(select(Attachment).where(Attachment.id == attachment_id,
            Attachment.user_id == user_id).with_for_update())
        if attachment is None or attachment.chat_id not in {None, chat_id}:
            raise HTTPException(404, "Attachment not found in this chat")
        attachment.chat_id = chat_id
        prompt += f"\n\nAttached document: {attachment.filename}\n<document>\n{attachment.text}\n</document>"
        if attachment.filename.lower().endswith(".csv"):
            prompt += "\nComputed numeric CSV statistics (blank cells ignored):\n" + json.dumps(csv_statistics(attachment.text))
    if len(prompt) > 60000:
        raise HTTPException(413, "Message and attachment exceed the 60,000 character limit.")
    return prompt
