from flask import Blueprint, session as flask_session, request, jsonify, redirect, url_for, render_template, flash

from db import Squire, Course, Team, engine, db_session, Team, TravelHistory, Quest, SquireQuestion, SquireRiddleProgress, Riddle, Enemy, Inventory, WizardItem, Job, MapFeature, MultipleChoiceQuestion, TrueFalseQuestion, ShopItem, SquireQuestStatus, TeamMessage, TreasureChest, XpThreshold, ChestHint, SquireQuestionAttempt, DungeonRooms
import logging
import random
from sqlalchemy import func

from utils.shared import ishint, iswordcounthint, iswordlengthhint

dungeon_bp = Blueprint('dungeon', __name__)

def get_current_dungeon_room(squire_id, pos, quest_id=39):
    x, y = pos
    db = db_session()

    return db.query(DungeonRooms).filter_by(
        squire_id=squire_id,
        quest_id=quest_id,
        x=x,
        y=y
    ).first()

def dungeon_room_exists(squire_id, pos, quest_id=39):
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
    pos = flask_session.get("dungeon_pos", (0, 0))

    # Load all rooms for this squire’s quest
    rooms = db.query(DungeonRooms).filter_by(
        squire_id=squire_id,
        quest_id=39
    ).all()

    # Convert to dict keyed by (x, y)
    room_dict = {(room.x, room.y): room for room in rooms}

    # Update current room as visited
    current_room = room_dict.get(pos)
    if current_room and not current_room.visited:
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
    room = get_current_dungeon_room(flask_session["squire_id"], current_pos)

    if direction not in room.allowed_directions:
        flash("🚧 A wall blocks your path.")
        return redirect(url_for("dungeon_map"))

    dx, dy = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}[direction]
    new_pos = (current_pos[0] + dx, current_pos[1] + dy)
    if not dungeon_room_exists(flask_session["squire_id"], new_pos):
        flash("That part of the dungeon is shrouded in mystery.")
        return redirect(url_for("dungeon.dungeon_map"))

    flask_session["dungeon_pos"] = new_pos
    return redirect(url_for("dungeon.dungeon_map"))

@dungeon_bp.route('/dungeon/mcq')
def present_mcq():
    db = db_session()
    squire_id = flask_session["squire_id"]
    pos = flask_session.get("dungeon_pos")
    quest_range = (33, 38)

    mcq = (
        db.query(MultipleChoiceQuestion)
        .filter(MultipleChoiceQuestion.quest_id.between(*quest_range))
        .order_by(func.rand())
        .first()
    )

    flask_session["current_question"] = {
        "id":            mcq.id,
        "text":          mcq.question_text,
        "options": {
            "A": mcq.optionA,
            "B": mcq.optionB,
            "C": mcq.optionC,
            "D": mcq.optionD,
        },
        "correctAnswer": mcq.correctAnswer
    }


    return render_template("dungeon_mcq.html", question=flask_session["current_question"], pos=pos)

@dungeon_bp.route('/dungeon/tf')
def present_tf():
    db = db_session()
    squire_id = flask_session["squire_id"]
    pos = flask_session.get("dungeon_pos")
    quest_range = (33, 38)

    question = (
        db.query(TrueFalseQuestion)
        .filter(TrueFalseQuestion.quest_id.between(*quest_range))
        .order_by(func.rand())
        .first()
    )


    return render_template("dungeon_tf.html", question=question, pos=pos)

@dungeon_bp.route('/dungeon/riddle')
def present_riddle():
    db = db_session()
    squire_id = flask_session["squire_id"]
    pos = flask_session.get("dungeon_pos")
    quest_range = (33, 38)

    r = (
        db.query(Riddle)
        .filter(Riddle.quest_id.between(*quest_range))
        .order_by(func.rand())
        .first()
    )
    show_hint = ishint(db, squire_id)
    show_word_count = iswordcounthint(db, squire_id)
    show_word_length = iswordlengthhint(db,squire_id)

    flask_session["current_riddle"] = {
        "id":               r.id,
        "text":             r.riddle_text,
        "answer":           r.answer,
        "hint":             r.hint,
        "word_length_hint": r.word_length_hint,
        "word_count":       r.word_count,
        "show_hint":        show_hint,
        "show_word_length": show_word_length,
        "show_word_count":  show_word_count
    }

    return render_template("dungeon_riddle.html", riddle=flask_session["current_riddle"], pos=pos, show_hint=show_hint, show_word_count=show_word_count)
