from db import db_session, Squire, TrueFalseQuestion, SquireQuestion, MultipleChoiceQuestion, Team, Quest, TextExtract
from services.progress import update_squire_progress
from sqlalchemy import func
import random
import logging
import fitz
from openai import OpenAI
import json
import os
import re

client = OpenAI(api_key=os.getenv("OPENAI_APIKEY"))


def get_textbook_excerpt(quest_id):
    #need to identify the quest learning objective and identify the appropriate section to send to API for quest generation

    # get the appropriate extract from TextExtract
    # and the applicable start and end pages based on the quest
    # randomly select a page from the range to extract to text
    # read with pdf reader
    # return extract

    db = db_session()

    try:
        te = db.query(TextExtract).filter_by(quest_id=quest_id).one_or_none()

        if not te:
            logging.warning(f"No text extract found for quest ID {quest_id}")
            return None

        start, end = te.page_start, te.page_end
        if start is None or end is None or start > end:
            logging.error(f"Invalid page range for quest {quest_id}: {start}–{end}")
            return None

        page_num = random.randint(start, end)

        # 3. Load the PDF from the /static folder
        pdf_path = os.path.join("static", te.book_name)
        if not os.path.exists(pdf_path):
            logging.error(f"PDF file not found: {pdf_path}")
            return None

        doc = fitz.open(pdf_path)

        if page_num - 1 >= len(doc):
            logging.error(f"Page {page_num} is out of bounds for file {te.book_name}")
            return None

        # 4. Extract the text from the chosen page
        page = doc[page_num - 1].get_text()  # fitz is zero-indexed
        doc.close()
        return page


    except Exception as e:
        logging.error(f"Error returning text section for extract {e}")

    finally:
        db.close()


def generate_openai_question(quest_id):

    excerpt = get_textbook_excerpt(quest_id)

    if not excerpt:
        logging.error(f"Error returning excerpt from text to send to API.")
        return None

    # Get learning objective from quest
    db = db_session()
    try:

        lo = db.query(Quest).filter_by(id=quest_id).one_or_none()
        objective = lo.learning_objective if lo else "Unknown Learning Objective"

    except Exception as e:
        logging.error(f"Could not retrieve learning objective: {e}")
        objective = "Unknown Objective"
    finally:
        db.close()

    system_prompt = f"You are an expert instructional designer that is generating items for game play in an educational game."

    user_prompt = f"""

Generate a multiple choice question from the Excerpt below related to the learning objective: {objective}

Respond in JSON ONLY with the following format:
    {{
      "question": "What is required for a contract to have valid consideration?",
      "options": {{
        "A": "An offer and acceptance",
        "B": "Mutual exchange of value",
        "C": "Written terms only",
        "D": "A witness signature"
      }},
      "correct_answer": "B"
    }}

IMPORTANT:
1. Be sure to randomly order the options and correct answer for each response.
2. Only return JSON formmatted above or the call will fail.

Excerpt:
{excerpt}

    """

    try:
        response = client.chat.completions.create(model="gpt-4",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7)
        content = response.choices[0].message.content
        return json.loads(content)

    except Exception as e:
        logging.error(f"💥 GPT API error during question generation: {e}")
        return None

def generate_npc_response(npc_type, context):
    """
    Generates an NPC response for a negotiation scenario using GPT.
    Args:
        npc_type (str): Type of NPC ("blacksmith", "trader", etc.)
        context (dict): Must include:
            - item_name (str)
            - offer (int): Player's current offer
            - base_price (int): For trader, or original price of the item
            - original_quote (int): For blacksmith (optional for others)
            - rounds (int): Current round number
    Returns:
        dict: {
            "reply_text": str,        # GPT-generated response text
            "counteroffer": int | None # Parsed counteroffer, or None if not found
        }
    """
    # ✅ NPC-specific tone/personality
    npc_profiles = {
        "blacksmith": {
            "system": "You are a gruff medieval blacksmith. Speak curtly, maybe sarcastically, but fair.",
            "template": (
                "Player offered {offer} bits to repair '{item_name}'. "
                "Your original quote was {original_quote} bits. "
                "This is round {rounds}. "
                "Respond as the blacksmith, keep it under 3 sentences. "
                "End with: [Counteroffer: X bits]."
            )
        },
        "trader": {
            "system": "You are a slick, clever wandering trader. Always sound charming and a bit greedy.",
            "template": (
                "Player offered {offer} bits for '{item_name}', normally worth {base_price} bits. "
                "This is round {rounds}. "
                "Respond as the trader, make it colorful but short. "
                "End with: [Counteroffer: X bits]."
            )
        }
    }

    if npc_type not in npc_profiles:
        raise ValueError(f"Unsupported NPC type: {npc_type}")

    npc_data = npc_profiles[npc_type]

    # ✅ Build the user prompt
    user_prompt = npc_data["template"].format(**context)

    # ✅ Call GPT
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": npc_data["system"]},
                {"role": "user", "content": user_prompt}
            ]
        )
        reply_text = response.choices[0].message.content

        # ✅ Parse counteroffer with improved regex
        counteroffer = None
        # Try multiple patterns to catch different formats
        patterns = [
            r"\[Counteroffer:\s*(\d+)\s*bits?\]",  # [Counteroffer: 44 bits]
            r"\[Counteroffer:\s*(\d+)\]",          # [Counteroffer: 44]
            r"Counteroffer:\s*(\d+)\s*bits?",      # Counteroffer: 44 bits
            r"(\d+)\s*bits?\s*\]",                 # 44 bits]
        ]

        for pattern in patterns:
            match = re.search(pattern, reply_text, re.IGNORECASE)
            if match:
                counteroffer = int(match.group(1))
                break

    except Exception as e:
        logging.error(f"GPT API error during NPC negotiation: {e}")
        return {
            "reply_text": "The NPC glares silently. (System error occurred)",
            "counteroffer": None
        }

    logging.debug(f"NPC={npc_type}, Offer={context['offer']}, Reply={reply_text}, Counter={counteroffer}")

    return {
        "reply_text": reply_text,
        "counteroffer": counteroffer
    }


def parse_counteroffer(text):
    """Extracts a numeric counteroffer from GPT response using [Counteroffer: X] pattern."""
    match = re.search(r"\[Counteroffer:\s*(\d+)\]", text)
    return int(match.group(1)) if match else None
