from sqlalchemy import func
import random

from db import Squire, Course, Team, engine, db_session, Team, TravelHistory, Quest, SquireQuestion, SquireRiddleProgress, Riddle, Enemy, Inventory, WizardItem, Job, MapFeature, MultipleChoiceQuestion, TrueFalseQuestion, ShopItem, SquireQuestStatus, TeamMessage, TreasureChest, XpThreshold, ChestHint, SquireQuestionAttempt, DungeonRooms


# Map question types to your models & SquireQuestion.question_type labels
QUESTION_MODELS = {
    "multiple_choice": ("mcq", MultipleChoiceQuestion),
    "true_false":      ("tf",  TrueFalseQuestion),
    "riddle":          ("riddle", Riddle),
}

DEFAULT_REVIEW_RULES = {
    "dungeon":     {"window": 6},  # last 6 quests in same course/curriculum
    "boss_arena":  {"window": None},
    "tournament":  {"window": 5},
    # per-type overrides allowed later via Encounter.rules_json
}

def _get_answered_ids(db, squire_id: int, question_type_key: str):
    """Set of question ids the squire already saw for this type."""
    rows = (
        db.query(SquireQuestion.question_id)
          .filter(
              SquireQuestion.squire_id == squire_id,
              SquireQuestion.question_type == question_type_key
          )
          .all()
    )
    return {qid for (qid,) in rows}

def _current_quest_info(db, quest_id: int):
    row = db.query(Quest.id, Quest.display_number, Quest.course_id, Quest.curriculum_key)\
            .filter(Quest.id == quest_id).first()
    if not row:
        return None, None, None, None
    return row.id, row.display_number, row.course_id, row.curriculum_key

def _source_quest_ids(db, quest_id: int, rules: dict):
    """
    Review pool = prior quests in SAME course (and same curriculum_key when available).
    Uses display_number if present; otherwise falls back to id ordering.
    """
    _, disp, course_id, cur_key = _current_quest_info(db, quest_id)
    window = rules.get("window")

    if disp is not None:
        base = db.query(Quest.id).filter(Quest.course_id == course_id)\
                                 .filter(Quest.display_number.isnot(None))\
                                 .filter(Quest.display_number < disp)\
                                 .order_by(Quest.display_number.desc())
        if cur_key:
            base = base.filter(Quest.curriculum_key == cur_key)
    else:
        base = db.query(Quest.id).filter(Quest.course_id == course_id)\
                                 .filter(Quest.id < quest_id)\
                                 .order_by(Quest.id.desc())

    if window and isinstance(window, int) and window > 0:
        base = base.limit(window)

    return [r.id for r in base.all()]

def _resolve_rules_for_mode(db, quest_id: int, mode: str, qtype: str = None):
    """
    Hook to pull Encounter.rules_json later. For now, defaults + optional per-type tweaks.
    """
    rules = dict(DEFAULT_REVIEW_RULES.get(mode or "dungeon", {}))
    # Example per-type tweak:
    # if qtype == "riddle":
    #     rules.setdefault("window", 8)
    return rules

def _random_first(query):
    """Better than ORDER BY RAND() for large sets; keeps RAND() as fallback."""
    try:
        count = query.count()
        if count == 0:
            return None
        off = random.randrange(count)
        return query.offset(off).first()
    except Exception:
        # Small sets or engines where COUNT() is pricey can just do RAND()
        return query.order_by(func.rand()).first()

def _pick_question(db, Model, source_quest_ids, exclude_ids, difficulty: str = None, tags: list[str] = None):
    q = db.query(Model).filter(Model.quest_id.in_(source_quest_ids))
    if hasattr(Model, "id"):
        q = q.filter(~Model.id.in_(exclude_ids)) if exclude_ids else q
    if difficulty and hasattr(Model, "difficulty"):
        q = q.filter(Model.difficulty == difficulty)
    # If you tag questions, add a join/contains here

    return _random_first(q)
