"""
Unified Question Service
Handles question selection, presentation, and validation across all fight types
(regular enemies, bosses, dungeons, tournaments)
"""
import logging
import random
import uuid
from typing import Optional, Tuple, Dict, Any, List

from sqlalchemy import func
from db import (
    db_session, Squire, Team, TrueFalseQuestion, MultipleChoiceQuestion,
    Riddle, SquireQuestion, SquireQuestionAttempt, SquireRiddleProgress
)
from utils.rules import (
    _get_answered_ids, _resolve_rules_for_mode,
    _source_quest_ids, _pick_question
)
from utils.api_calls import generate_openai_question


class QuestionContext:
    """Context for question presentation and validation"""
    def __init__(self, source: str, enemy: dict = None, boss: dict = None,
                 pending_job: dict = None, mode: str = None):
        self.source = source  # "enemy", "boss", "dungeon", "tournament"
        self.enemy = enemy or {}
        self.boss = boss or {}
        self.pending_job = pending_job
        self.mode = mode


class QuestionResult:
    """Result of question validation"""
    def __init__(self, correct: bool, message: str, xp_reward: int = 0,
                 gold_reward: int = 0, hint: str = None, special_item: str = None):
        self.correct = correct
        self.message = message
        self.xp_reward = xp_reward
        self.gold_reward = gold_reward
        self.hint = hint
        self.special_item = special_item


def select_question(
    db,
    squire_id: int,
    quest_id: int,
    question_type: str,
    mode: str = None,
    level: int = 1,
    exclude_recent: List[int] = None
) -> Optional[Any]:
    """
    Unified question selection for all fight types.

    Args:
        db: Database session
        squire_id: ID of the squire
        quest_id: Current quest ID
        question_type: "true_false", "multiple_choice", "riddle", or "api_question"
        mode: Optional mode ("boss_arena", "dungeon", "tournament", "dungeonboss")
        level: Player level (for determining question complexity)
        exclude_recent: Optional list of question IDs to exclude

    Returns:
        Question object or None if no question available
    """
    try:
        # Get answered IDs for this question type
        answered_ids = _get_answered_ids(db, squire_id, question_type)

        # Add recently seen questions to exclusion list
        if exclude_recent:
            answered_ids = answered_ids.union(set(exclude_recent))

        # Resolve rules based on mode
        qtype_map = {
            "true_false": "tf",
            "multiple_choice": "mcq",
            "riddle": "riddle"
        }
        rules = _resolve_rules_for_mode(
            db, quest_id, mode or "enemy",
            qtype=qtype_map.get(question_type, "mcq")
        )

        # Get source quest IDs based on rules
        source_ids = _source_quest_ids(db, quest_id, rules)
        if not source_ids:
            logging.warning(f"No source quest IDs for quest {quest_id}, mode {mode}")
            return None

        # Handle API-generated questions
        if question_type == "api_question":
            # Pick a random quest from the source IDs
            selected_quest = random.choice(source_ids) if len(source_ids) > 1 else source_ids[0]
            return generate_openai_question(selected_quest - 1)  # API uses 0-based indexing

        # Select question model
        question_model = {
            "true_false": TrueFalseQuestion,
            "multiple_choice": MultipleChoiceQuestion,
            "riddle": Riddle
        }.get(question_type)

        if not question_model:
            logging.error(f"Unknown question type: {question_type}")
            return None

        # Pick question using shared logic
        question = _pick_question(
            db,
            question_model,
            source_quest_ids=source_ids,
            exclude_ids=answered_ids,
            difficulty=rules.get("difficulty")
        )

        return question

    except Exception as e:
        logging.exception(f"Error selecting question: {e}")
        return None


def prepare_question_data(question, question_type: str) -> Dict[str, Any]:
    """
    Prepare question data for template rendering.

    Args:
        question: Question object or dict (for API questions)
        question_type: Type of question

    Returns:
        Dictionary with question data for template
    """
    if question_type == "api_question":
        # API question is already a dict
        return {
            "id": "api",
            "type": "api_generated",
            "text": question["question"],
            "options": question["options"],
            "correct_answer": question["correct_answer"]
        }
    elif question_type == "true_false":
        return {
            "id": question.id,
            "text": question.question,
            "type": "true_false"
        }
    elif question_type == "multiple_choice":
        return {
            "id": question.id,
            "text": question.question_text,
            "type": "multiple_choice",
            "options": {
                "A": question.optionA,
                "B": question.optionB,
                "C": question.optionC,
                "D": question.optionD
            },
            "correctAnswer": question.correctAnswer
        }
    elif question_type == "riddle":
        return {
            "id": question.id,
            "riddle_text": question.riddle_text,
            "answer": question.answer,
            "hint": getattr(question, "hint", None),
            "word_length_hint": getattr(question, "word_length_hint", None),
            "word_count": getattr(question, "word_count", None),
            "type": "riddle"
        }
    else:
        return {}


def get_template_for_context(question_type: str, context: QuestionContext) -> str:
    """
    Get the appropriate template for rendering based on question type and context.

    Args:
        question_type: Type of question
        context: Question context (source, mode, etc.)

    Returns:
        Template name
    """
    if context.source == "dungeon":
        template_map = {
            "true_false": "dungeon_tf.html",
            "multiple_choice": "dungeon_mcq.html",
            "riddle": "dungeon_riddle.html"
        }
        return template_map.get(question_type, "answer_question.html")
    elif context.mode == "tournament":
        return "tourney_combat.html"
    elif context.source == "boss" or context.mode in ["boss_arena", "dungeonboss"]:
        return "boss_combat.html"
    else:
        # Regular enemy encounters
        if question_type == "true_false":
            return "answer_question.html"
        else:
            return "answer_question_mc.html"


def validate_answer(
    db,
    squire_id: int,
    quest_id: int,
    question,
    question_type: str,
    user_answer: str,
    context: QuestionContext
) -> QuestionResult:
    """
    Unified answer validation for all question types.

    Args:
        db: Database session
        squire_id: ID of the squire
        quest_id: Current quest ID
        question: Question object or dict
        question_type: Type of question
        user_answer: User's submitted answer
        context: Question context

    Returns:
        QuestionResult with validation outcome
    """
    try:
        # Determine if answer is correct
        is_correct = _check_correctness(question, question_type, user_answer)

        # Calculate rewards based on context
        xp_reward, gold_reward = _calculate_rewards(context, is_correct)

        # Record the attempt
        _record_attempt(db, squire_id, quest_id, question, question_type, is_correct)

        # Get hint if incorrect
        hint = None
        if not is_correct and question_type != "api_question":
            hint = getattr(question, "hint", None)

        # Build result message
        if is_correct:
            message = _build_success_message(context, xp_reward, gold_reward)
        else:
            message = _build_failure_message(context, hint)

        return QuestionResult(
            correct=is_correct,
            message=message,
            xp_reward=xp_reward,
            gold_reward=gold_reward,
            hint=hint
        )

    except Exception as e:
        logging.exception(f"Error validating answer: {e}")
        return QuestionResult(
            correct=False,
            message=f"Error validating answer: {e}",
            xp_reward=0,
            gold_reward=0
        )


def _check_correctness(question, question_type: str, user_answer: str) -> bool:
    """Check if the user's answer is correct"""
    user_answer = user_answer.strip().upper()

    if question_type == "api_question":
        return user_answer == question["correct_answer"].upper()
    elif question_type == "true_false":
        correct_bool = bool(question.correct_answer)
        return (user_answer == "T" and correct_bool) or (user_answer == "F" and not correct_bool)
    elif question_type == "multiple_choice":
        return user_answer == question.correctAnswer.upper()
    elif question_type == "riddle":
        return user_answer.lower() == question.answer.strip().lower()

    return False


def _calculate_rewards(context: QuestionContext, is_correct: bool) -> Tuple[int, int]:
    """Calculate XP and gold rewards based on context and correctness"""
    if not is_correct:
        return 0, 0

    # Dungeon rewards
    if context.source == "dungeon":
        if context.mode == "treasure":
            return 25, 25
        else:
            return 10, 10

    # Boss/tournament rewards - handled separately by hunger system
    if context.source == "boss" or context.mode in ["boss_arena", "tournament", "dungeonboss"]:
        return 0, 0

    # Regular enemy rewards
    xp = context.enemy.get("xp_reward", 0)
    gold = context.enemy.get("gold_reward", 0)

    return xp, gold


def _record_attempt(db, squire_id: int, quest_id: int, question,
                   question_type: str, is_correct: bool):
    """Record the question attempt in the database"""
    try:
        # Get question ID
        if question_type == "api_question":
            question_id = -1  # API questions use -1
        elif question_type == "riddle":
            question_id = question.id
            # Record riddle progress separately
            db.add(SquireRiddleProgress(
                squire_id=squire_id,
                riddle_id=question.id,
                quest_id=quest_id,
                answered_correctly=is_correct
            ))
        else:
            question_id = question.id

        # Record attempt
        attempt = SquireQuestionAttempt(
            squire_id=squire_id,
            question_id=question_id,
            question_type=question_type,
            answered_correctly=is_correct,
            quest_id=quest_id
        )
        db.add(attempt)

        # Update or create SquireQuestion record if correct
        if is_correct:
            sq = (
                db.query(SquireQuestion)
                .filter_by(
                    squire_id=squire_id,
                    question_id=question_id,
                    question_type=question_type
                )
                .one_or_none()
            )

            if not sq:
                sq = SquireQuestion(
                    squire_id=squire_id,
                    question_id=question_id,
                    question_type=question_type,
                    answered_correctly=True
                )
                db.add(sq)
            else:
                sq.answered_correctly = True

        db.commit()

    except Exception as e:
        logging.exception(f"Error recording attempt: {e}")
        db.rollback()


def _build_success_message(context: QuestionContext, xp: int, gold: int) -> str:
    """Build success message based on context"""
    if context.pending_job:
        payout = random.randint(
            context.pending_job["min_payout"],
            context.pending_job["max_payout"]
        )
        return f"✅ You completed '{context.pending_job['job_name']}' and earned 💰 {payout} bits!"

    if context.source == "dungeon":
        return f"✅ Correct! You gained {xp} XP and {gold} bits."

    enemy_name = context.enemy.get("name", "the enemy")
    return f"✅ Correct! You have defeated {enemy_name} and earned {xp} XP and {gold} bits."


def _build_failure_message(context: QuestionContext, hint: str = None) -> str:
    """Build failure message based on context"""
    if context.pending_job:
        hint_text = f" Here's a hint: {hint}" if hint else ""
        return f"❌ Incorrect! You failed the task and earned nothing.{hint_text}"

    enemy_name = context.enemy.get("name", "the enemy")
    base_msg = f"❌ Incorrect! You are defeated by {enemy_name} and lose some experience points!"

    if hint:
        return f"{base_msg}\n{hint}"

    return base_msg
