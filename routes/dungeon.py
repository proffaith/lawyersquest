from flask import Blueprint, session as flask_session, request, jsonify, redirect, url_for, render_template, flash

from db import Squire, Course, Team, engine, db_session, Team, TravelHistory, Quest, SquireQuestion, SquireRiddleProgress, Riddle, Enemy, Inventory, WizardItem, Job, MapFeature, MultipleChoiceQuestion, TrueFalseQuestion, ShopItem, SquireQuestStatus, TeamMessage, TreasureChest, XpThreshold, ChestHint, SquireQuestionAttempt, DungeonRooms
import logging
import random
from sqlalchemy import func

from utils.shared import ishint, iswordcounthint, iswordlengthhint
from utils.shared import calculate_riddle_reward

from utils.shared import get_squire_stats
from utils.shared import calculate_hit_chance
from utils.shared import calculate_enemy_encounter_probability
from utils.shared import update_work_for_combat
from utils.shared import get_player_max_hunger
from utils.shared import mod_enemy_hunger
from utils.shared import combat_mods
from utils.shared import hunger_mods
from utils.shared import degrade_gear

from utils.rules import _get_answered_ids,_current_quest_info,_source_quest_ids,_resolve_rules_for_mode,_pick_question

dungeon_bp = Blueprint('dungeon', __name__)

def get_current_dungeon_room(squire_id, pos, quest_id):
    x, y = pos
    db = db_session()

    return db.query(DungeonRooms).filter_by(
        squire_id=squire_id,
        quest_id=quest_id,
        x=x,
        y=y
    ).first()

def dungeon_room_exists(squire_id, pos, quest_id):
    x, y = pos
    db = db_session()
    return db.query(DungeonRooms).filter_by(
        squire_id=squire_id,
        quest_id=quest_id,
        x=x,
        y=y
    ).first() is not None


@dungeon_bp.route('/dungeon')
def dungeon_map():
    db = db_session()

    squire_id = flask_session["squire_id"]
    quest_id = flask_session["quest_id"]
    pos = flask_session.get("dungeon_pos", (0, 0))

    if isinstance(pos, list):
        pos = tuple(pos)
    elif not isinstance(pos, tuple):
        # last defensive fallback
        try:
            pos = tuple(pos)
        except Exception:
            pos = (0, 0)

    # Load all rooms for this squire’s quest
    rooms = db.query(DungeonRooms).filter_by(
        squire_id=squire_id,
        quest_id=quest_id
    ).all()

    

    # Convert to dict keyed by (x, y)
    room_dict = {(room.x, room.y): room for room in rooms}

    # Resolve the current room from position (may still be missing if pos is stale)
    current_room = room_dict.get(pos)

    # If session pos is stale (no such room), fall back to a safe room (0,0) or last visited
    if current_room is None:
        fallback = room_dict.get((0, 0)) or next(iter(room_dict.values()))
        current_room = fallback
        pos = (current_room.x, current_room.y)
        flask_session["dungeon_pos"] = list(pos)

    # Update current room as visited (ensure booleans are non-null)
    if getattr(current_room, "visited", False) is False:
        current_room.visited = True
        db.commit()

#~~~~~~~~~~~~~~~~~~~~~~ Routing for Room Type
    combat_result=flask_session.pop("combat_result", "")
    success=flask_session.pop("success", "")

    if combat_result:
        if success:
            #update this room to indicate answered already
            current_room.answered = True
            db.commit()

        return render_template("dungeon.html", rooms=room_dict, current_pos=pos, current_room=current_room, combat_result=combat_result)

    else:

        if current_room.answered == False:

            if current_room.room_type == "mcq":
                logging.debug(f"Redirecting to room type handler: {current_room.room_type}")

                return redirect(url_for("dungeon.present_mcq"))

            elif current_room.room_type == "riddle":
                logging.debug(f"Redirecting to room type handler: {current_room.room_type}")

                return redirect(url_for("dungeon.present_riddle"))

            elif current_room.room_type == "true_false":
                logging.debug(f"Redirecting to room type handler: {current_room.room_type}")

                return redirect(url_for("dungeon.present_tf"))

            elif current_room.room_type == "treasure":
                logging.debug(f"Redirecting to room type handler: {current_room.room_type}")

                return redirect(url_for("dungeon.present_treasure"))

            elif current_room.room_type == "boss":
                logging.debug(f"Redirecting to room type handler: {current_room.room_type}")

                return redirect(url_for("dungeon.boss_battle"))

        return render_template("dungeon.html", rooms=room_dict, current_pos=pos, current_room=current_room)

@dungeon_bp.route('/dungeon/move/<direction>', methods=["POST"])
def move_in_dungeon(direction):
    current_pos = flask_session.get("dungeon_pos")
    quest_id = flask_session.get("quest_id")
    room = get_current_dungeon_room(flask_session["squire_id"], current_pos, quest_id)

    if direction not in room.allowed_directions:
        flash("🚧 A wall blocks your path.")
        return redirect(url_for("dungeon.dungeon_map"))

    dx, dy = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}[direction]
    new_pos = (current_pos[0] + dx, current_pos[1] + dy)
    if not dungeon_room_exists(flask_session["squire_id"], new_pos, quest_id):
        flash("That part of the dungeon is shrouded in mystery.")
        return redirect(url_for("dungeon.dungeon_map"))

    flask_session["dungeon_pos"] = new_pos
    return redirect(url_for("dungeon.dungeon_map"))

@dungeon_bp.route('/dungeon/mcq')
def present_mcq():
    squire_id = flask_session.get("squire_id")
    quest_id  = flask_session.get("quest_id")
    mode      = flask_session.get("mode") or "dungeon"
    pos       = flask_session.get("dungeon_pos")

    if not squire_id or not quest_id:
        return redirect(url_for("login"))

    with db_session() as db:
        answered_ids = _get_answered_ids(db, squire_id, "multiple_choice")
        rules = _resolve_rules_for_mode(db, quest_id, mode, qtype="mcq")
        source_ids = _source_quest_ids(db, quest_id, rules)
        if not source_ids:
            flask_session["battle_summary"] = "No prior content to review yet. You must flee!"
            return redirect(url_for("ajax_handle_boss_combat"))

        mcq = _pick_question(db, MultipleChoiceQuestion, source_ids, answered_ids,
                             difficulty=rules.get("difficulty"))
        if not mcq:
            flask_session["battle_summary"] = "No question available. You must flee!"
            return redirect(url_for("ajax_handle_boss_combat"))

        flask_session["current_question"] = {
            "id":            mcq.id,
            "text":          mcq.question_text,
            "options": {
                "A": mcq.optionA, "B": mcq.optionB, "C": mcq.optionC, "D": mcq.optionD,
            },
            "correctAnswer": mcq.correctAnswer
        }
        # Optional per-session dedupe so players don't see repeats in one run
        recent = set(flask_session.get("recent_mcq_ids", [])); recent.add(mcq.id)
        flask_session["recent_mcq_ids"] = list(recent)[-20:]

        return render_template("dungeon_mcq.html",
                               question=flask_session["current_question"], pos=pos)


@dungeon_bp.route('/dungeon/tf')
def present_tf():
    squire_id = flask_session.get("squire_id")
    quest_id  = flask_session.get("quest_id")
    mode      = flask_session.get("mode") or "dungeon"
    pos       = flask_session.get("dungeon_pos")

    if not squire_id or not quest_id:
        return redirect(url_for("login"))

    with db_session() as db:
        answered_ids = _get_answered_ids(db, squire_id, "true_false")
        rules = _resolve_rules_for_mode(db, quest_id, mode, qtype="tf")
        source_ids = _source_quest_ids(db, quest_id, rules)
        if not source_ids:
            flash("Nothing to review yet.")
            return redirect(url_for("dungeon.dungeon_map"))

        tfq = _pick_question(db, TrueFalseQuestion, source_ids, answered_ids,
                             difficulty=rules.get("difficulty"))
        if not tfq:
            flash("No TF question available.")
            return redirect(url_for("dungeon.dungeon_map"))

        return render_template("dungeon_tf.html", question=tfq, pos=pos)


@dungeon_bp.route('/dungeon/riddle')
def present_riddle():
    squire_id = flask_session.get("squire_id")
    quest_id  = flask_session.get("quest_id")
    mode      = flask_session.get("mode") or "dungeon"
    pos       = flask_session.get("dungeon_pos")

    if not squire_id or not quest_id:
        return redirect(url_for("login"))

    with db_session() as db:
        answered_ids = _get_answered_ids(db, squire_id, "riddle")
        rules = _resolve_rules_for_mode(db, quest_id, mode, qtype="riddle")
        source_ids = _source_quest_ids(db, quest_id, rules)
        if not source_ids:
            flash("No riddles to review yet.")
            return redirect(url_for("dungeon.dungeon_map"))

        r = _pick_question(db, Riddle, source_ids, answered_ids,
                           difficulty=rules.get("difficulty"))
        if not r:
            flash("No riddle available.")
            return redirect(url_for("dungeon.dungeon_map"))

        show_hint        = ishint(db, squire_id)
        show_word_count  = iswordcounthint(db, squire_id)
        show_word_length = iswordlengthhint(db, squire_id)

        riddle_session = flask_session.get("riddle_attempts", {})
        riddle_session.setdefault("attempt_count", 0)
        riddle_session.setdefault("all_attempts", [])
        riddle_session.setdefault("partial_words_found", [])
        flask_session["riddle_attempts"] = riddle_session

        flask_session["current_riddle"] = {
            "id":               r.id,
            "riddle_text":      r.riddle_text,
            "answer":           r.answer,
            "hint":             r.hint,
            "word_length_hint": r.word_length_hint,
            "word_count":       r.word_count,
            "show_hint":        show_hint,
            "show_word_length": show_word_length,
            "show_word_count":  show_word_count
        }

        return render_template("dungeon_riddle.html",
                               riddle=flask_session["current_riddle"],
                               pos=pos, show_hint=show_hint,
                               show_word_count=show_word_count)

@dungeon_bp.route('/dungeon/treasure')
def present_treasure():
    squire_id = flask_session.get("squire_id")
    quest_id  = flask_session.get("quest_id")
    mode      = flask_session.get("mode") or "dungeon"
    pos       = flask_session.get("dungeon_pos")

    if not squire_id or not quest_id:
        return redirect(url_for("login"))

    with db_session() as db:
        answered_ids = _get_answered_ids(db, squire_id, "riddle")
        rules = _resolve_rules_for_mode(db, quest_id, mode, qtype="riddle")
        source_ids = _source_quest_ids(db, quest_id, rules)
        r = _pick_question(db, Riddle, source_ids, answered_ids,
                           difficulty=rules.get("difficulty"))
        if not r:
            flash("No treasure riddle available.")
            return redirect(url_for("dungeon.dungeon_map"))

        show_hint = ishint(db, squire_id)

        flask_session["current_treasure_riddle"] = {
            "id": r.id,
            "riddle_id": r.id,
            "riddle_text": r.riddle_text,
            "answer": r.answer,
            "hint": r.hint if show_hint else None,
            "difficulty": getattr(r, "difficulty", None),
            "gold_reward": 25,
            "xp_reward": 25,
        }

        return render_template("dungeon_treasure.html",
                               chest=flask_session["current_treasure_riddle"], pos=pos)



@dungeon_bp.route('/dungeon/check_treasure', methods=["POST"])
def check_treasure():
    squire_id = flask_session.get("squire_id")
    quest_id = flask_session.get("quest_id")
    current = flask_session.get("current_treasure_riddle")

    if not squire_id or not current:
        return jsonify(success=False, message="No active treasure chest!")

    user_answer = request.form.get("answer", "").strip().lower()
    correct_answer = current["answer"].strip().lower()

    db = db_session()
    try:
        if user_answer == correct_answer:
            riddle_id = current["riddle_id"]
            gold_reward = current.get("gold_reward", 0)
            xp_reward = current.get("xp_reward", 0)

            db.add(SquireRiddleProgress(
                squire_id=squire_id,
                riddle_id=riddle_id,
                quest_id=quest_id,
                answered_correctly=True,
            ))

            sq = (
                db.query(SquireQuestion)
                .filter_by(squire_id=squire_id, question_id=riddle_id, question_type="riddle")
                .one_or_none()
            )
            if not sq:
                db.add(SquireQuestion(
                    squire_id=squire_id,
                    question_id=riddle_id,
                    question_type="riddle",
                    answered_correctly=True,
                ))
            else:
                sq.answered_correctly = True

            team = db.query(Team).get(db.query(Squire).get(squire_id).team_id)
            if gold_reward:
                team.gold += gold_reward
                team.reputation += 2

            squire = db.query(Squire).get(squire_id)
            if xp_reward:
                squire.experience_points += xp_reward

            special_item = calculate_riddle_reward(squire_id, riddle_id)

            db.commit()

            message = f"✅ Correct! You gained {xp_reward} XP, {gold_reward} bitcoin, and {special_item}."
            flask_session["combat_result"] = (
                f"✅ Correct! You gained {xp_reward} XP, {gold_reward} bitcoin and {special_item}."
            )
            flask_session["success"] = True
            flask_session.modified = True  # ← This is critical!

            return jsonify(success=True, message=message)
        else:
            return jsonify(success=False, message="❌ Incorrect! Try again.")
    except Exception as e:
        db.rollback()
        logging.error(f"Error checking dungeon treasure: {e}")
        return jsonify(success=False, message="An error occurred.")
    finally:
        db.close()



@dungeon_bp.route('/dungeon/boss')
def boss_battle():
    """Initialize the dungeon boss encounter."""
    squire_id = flask_session.get("squire_id")
    quest_id = flask_session.get("quest_id")

    if not squire_id or not quest_id:
        return redirect(url_for("dungeon.dungeon_map"))

    db = db_session()
    try:
        boss = (
            db.query(Enemy)
              .filter(Enemy.is_boss == True)
              .order_by(func.rand())
              .first()
        )

        if not boss:
            flash("No boss found.")
            return redirect(url_for("dungeon.dungeon_map"))

        flask_session["boss"] = {
            "id":           boss.id,
            "name":         boss.enemy_name,
            "description":  boss.description,
            "weakness":     boss.weakness,
            "gold_reward":  boss.gold_reward,
            "xp_reward":    boss.xp_reward,
            "max_hunger":   boss.max_hunger,
            "static_image": boss.static_image,
        }

        flask_session["mode"] = "dungeonboss"

        max_hunger, _ = get_player_max_hunger(squire_id)
        player_max_hunger = min(max_hunger + hunger_mods(squire_id), 8)

        flask_session["player_current_hunger"] = 0
        flask_session["boss_current_hunger"] = 0
        flask_session["player_max_hunger"] = int(player_max_hunger)
        flask_session["boss_max_hunger"] = int(boss.max_hunger)

    finally:
        db.close()

    return redirect(url_for("questions.answer_MC_question"))
