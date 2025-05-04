import fitz
from rapidfuzz import fuzz
import pymysql
import os
from dotenv import load_dotenv
# Load environment variables at the start of the application
load_dotenv()

def dbconnect():
    return pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        ssl={"ssl": {}},
        connect_timeout=10
    )

def extract_text_by_page(pdf_path):
    doc = fitz.open(pdf_path)
    page_text = {}
    for i in range(len(doc)):
        text = doc[i].get_text()
        page_text[i+1] = text
    return page_text


def find_best_hint_page(question_text, page_text):
    best_score = 0
    best_page = None
    for page_num, text in page_text.items():
        score = fuzz.token_set_ratio(question_text.lower(), text.lower())
        if score > best_score:
            best_score = score
            best_page = page_num
    return best_page, best_score

try:
    conn = dbconnect()
    cursor = conn.cursor()
    page_text = extract_text_by_page('/users/timfaith/sites/static/MNGT140OER.pdf')

    cursor.execute("SELECT id, question from true_false_questions where hint IS NULL;")
    questions = cursor.fetchall()

    for id, q in questions:

        best_page, best_score = find_best_hint_page(q,page_text)

        hint = f"See textbook page {best_page}"
        cursor.execute(
            "UPDATE true_false_questions SET hint = %s WHERE id = %s",
            (hint, id)
        )
        conn.commit()

    cursor.execute("SELECT id, question_text,quest_id FROM multiple_choice_questions WHERE hint IS NULL;")
    mcs = cursor.fetchall()

    for id, q, qid in mcs:
        #based on qid, identify the appropriate lecture transcript from a dictionary

        if qid in (1,2,3,4):
            page_text = extract_text_by_page('/users/timfaith/sites/static/U1L1Transcript.pdf')
            module = "Unit 1 Module 1"

        if qid in (5,6,7):
            page_text = extract_text_by_page('/users/timfaith/sites/static/U1L2Transcript.pdf')
            module = "Unit 1 Module 2"

        if qid in (8,9):
            page_text = extract_text_by_page('/users/timfaith/sites/static/U1L3Transcript.pdf')
            module = "Unit 1 Module 3"

        if qid in (10,12,13):
            page_text = extract_text_by_page('/users/timfaith/sites/static/U1L4Transcript.pdf')
            module = "Unit 1 Module 4"

        best_page, best_score = find_best_hint_page(q,page_text)


        hint = f"See Lecture Transcript for {module} on page {best_page}"
        cursor.execute(
            "UPDATE multiple_choice_questions SET hint = %s WHERE id = %s",
            (hint, id)
        )
        conn.commit()


except Exception as e:
    print(f"Oh shit {e}")
