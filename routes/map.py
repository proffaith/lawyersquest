# Map-related routes
from flask import Blueprint, session as flask_session, request, jsonify, redirect, url_for, render_template, flash

from db import (
    Squire, Course, Team, engine, db_session, Team, TravelHistory,
    Quest, SquireQuestion, SquireRiddleProgress, Riddle, Enemy,
    Inventory, WizardItem, Job, MapFeature, MultipleChoiceQuestion,
    TrueFalseQuestion, ShopItem, SquireQuestStatus, TeamMessage, TreasureChest,
    XpThreshold, ChestHint, SquireQuestionAttempt, DungeonRooms,
    MapNode
    )

from sqlalchemy import create_engine, func, and_, select
from services.progress import update_player_position
import logging
import random

from utils.shared import get_squire_stats
from utils.shared import check_quest_completion
from utils.shared import complete_quest
from utils.shared import get_random_riddle
from utils.shared import check_riddle_answer
from utils.shared import get_active_quests
from utils.shared import chooseq
from utils.shared import get_riddles_for_quest
from utils.shared import get_inventory
#from utils.shared import visit_shop
from utils.shared import consume_food
from utils.shared import get_hunger_bar
#from utils.shared import check_for_treasure
#from utils.shared import open_treasure_chest
from utils.shared import check_quest_progress
from utils.shared import display_progress_bar
from utils.shared import generate_word_length_hint
from utils.shared import update_riddle_hints
from utils.shared import display_travel_map
from utils.shared import check_for_treasure_at_location
from utils.shared import calculate_hit_chance
from utils.shared import get_viewport_map
from utils.shared import calculate_enemy_encounter_probability
from utils.shared import update_work_for_combat
from utils.shared import get_player_max_hunger
from utils.shared import mod_enemy_hunger
from utils.shared import calculate_riddle_reward
from utils.shared import combat_mods
from utils.shared import hunger_mods
from utils.shared import degrade_gear
from utils.shared import ishint
from utils.shared import iswordcounthint
from utils.shared import iswordlengthhint
from utils.shared import flee_safely
from utils.shared import calc_flee_safely
from utils.shared import add_team_message
from utils.shared import check_for_level_up

from utils.shared import generate_dungeon
from utils.shared import update_squire_question_attempt
from utils.shared import update_squire_question
from utils.shared import generate_first_letter_hint
from utils.shared import check_partial_match


map_bp = Blueprint('map', __name__)

def get_allowed_directions(coord, all_coords):
    x, y = coord
    directions = ""
    if (x, y - 1) in all_coords:
        directions += "N"
    if (x, y + 1) in all_coords:
        directions += "S"
    if (x + 1, y) in all_coords:
        directions += "E"
    if (x - 1, y) in all_coords:
        directions += "W"
    return directions


from sqlalchemy.dialects.mysql import insert as mysql_insert
from typing import Iterable, Tuple, List, Dict

Coord = Tuple[int, int]
RoomTuple = Tuple[int, int, str]  # (x, y, room_type)

DIRS = {
    "N": (0, -1),
    "S": (0,  1),
    "E": (1,  0),
    "W": (-1, 0),
}

def compute_allowed_directions(room_data: Iterable[RoomTuple]) -> List[Dict]:
    """
    room_data: iterable of (x, y, room_type)
    returns a list of dicts ready for insert/upsert with allowed_directions filled.
    """
    # Dedupe coords (path generators sometimes repeat)
    unique = {}
    for x, y, room_type in room_data:
        unique[(x, y)] = room_type

    coords = set(unique.keys())

    rows = []
    for (x, y), room_type in unique.items():
        allowed = []
        for d, (dx, dy) in DIRS.items():
            nx, ny = x + dx, y + dy
            if (nx, ny) in coords:
                allowed.append(d)
        # Sort for stable UI/debug (e.g., "ENWS" vs "NEWS" — pick one)
        allowed_str = "".join(sorted(allowed))
        rows.append({
            "x": x,
            "y": y,
            "room_type": room_type,
            "allowed_directions": allowed_str,
        })
    return rows


def insert_dungeon_to_db(room_data, squire_id, quest_id) -> bool:
    """
    room_data: list of (x, y, room_type) tuples
    """
    if squire_id is None or quest_id is None:
        raise ValueError(f"squire_id/quest_id must not be None (got {squire_id=}, {quest_id=})")

    db = db_session()
    try:
        # 1) Compute allowed_directions once
        ad_rows = compute_allowed_directions(room_data)  # [{x,y,room_type,allowed_directions}, ...]

        # 2) Merge with IDs + defaults (and dedupe by (x,y))
        seen = set()
        rows = []
        for r in ad_rows:
            x, y = r["x"], r["y"]
            if (x, y) in seen:
                continue
            seen.add((x, y))
            rows.append({
                "squire_id": squire_id,
                "quest_id": quest_id,
                "x": x,
                "y": y,
                "room_type": r["room_type"],
                "allowed_directions": r["allowed_directions"],
                "visited": False,
                "locked": False,
                "answered": False,
            })

        if not rows:
            return True

        # 3) Upsert (don’t clobber progress; do refresh static fields)
        stmt = mysql_insert(DungeonRooms.__table__).values(rows)
        upsert = stmt.on_duplicate_key_update(
            room_type=stmt.inserted.room_type,
            allowed_directions=stmt.inserted.allowed_directions,
            # keep visited/answered/locked as-is to preserve player progress
        )
        db.execute(upsert)
        db.commit()
        return True

    except Exception:
        db.rollback()
        current_app.logger.exception("insert_dungeon_to_db failed")
        return False



def dungeon_exists(squire_id: int, quest_id: int) -> bool:
    db = db_session()

    return db.query(DungeonRooms).filter_by(
        squire_id=squire_id,
        quest_id=quest_id
    ).first() is not None

def init_riddle_session(riddle_id):
    """Initialize or reset riddle session data."""
    flask_session["riddle_attempts"] = {
        "riddle_id": riddle_id,
        "attempt_count": 0,
        "partial_words_found": [],
        "all_attempts": []  # Optional: store history of attempts
    }

def get_riddle_session():
    """Get current riddle session data."""
    return flask_session.get("riddle_attempts", {})

def clear_riddle_session():
    """Clear riddle session data."""
    flask_session.pop("riddle_attempts", None)
    flask_session.pop("riddle_feedback", None)

def get_node_type(x: int, y: int, quest_id: int):
    with db_session() as session:
        stmt = (
            select(MapNode.node_type)
            .where(MapNode.x == x, MapNode.y == y, MapNode.quest_id == quest_id)
        )
        #print(f"{stmt}")
        return session.scalar(stmt)  # returns 'quest' | 'boss_arena' | 'dungeon' | None


@map_bp.route('/ajax_move', methods=['POST'])
def ajax_move():
    """Handle player movement with proper database transaction management."""
    event = None
    message = ""
    x = y = tm = None

    # Get session data
    squire_id = flask_session.get("squire_id")
    quest_id = flask_session.get("quest_id")
    squire_quest_id = flask_session.get("squire_quest_id")

    # Validate session
    if not squire_id:
        return jsonify({"error": "Session expired. Please log in again."}), 400

    # Get movement direction from AJAX request
    direction = request.json.get("direction")

    # Create database session with context manager for proper cleanup
    with db_session() as db:
        try:
            # Get current level
            level = db.query(Squire.level).filter(Squire.id == squire_id).scalar()
            flask_session["level"] = level

            # Get current position (used as fallback)
            current_position = db.query(Squire.x_coordinate, Squire.y_coordinate).filter(Squire.id == squire_id).one()
            x, y = current_position


            new_level = check_for_level_up(squire_id,db)
            if new_level:
                new_level = flask_session.pop("new_level", None)
                flask_session.pop("leveled_up", None)

                return render_template("level_up.html", level=new_level)


            # Process movement based on direction
            if direction in ("N", "S", "E", "W"):
                # Check food requirement
                ok, food_message = consume_food(squire_id)
                if not ok:
                    game_map = get_viewport_map(db, squire_id, quest_id, 15)
                    return jsonify({
                        "map": game_map,
                        "position": (x, y),
                        "message": food_message,      # "You have no food!"
                        "level": level,
                    })

                # Update player position (with transaction)
                x, y, tm = update_player_position(db, squire_id, direction)
                db.commit()  # Ensure position update is committed

                event_type = get_node_type(x, y, quest_id)

                if food_message:
                    message = f"{food_message} \n {tm}"

                # Calculate combat probability
                p = calculate_enemy_encounter_probability(squire_id, quest_id, x, y, squire_quest_id)
                logging.debug(f"Combat Probability: {p}")

                # Check for quest completion
                if check_quest_completion(squire_id, quest_id):
                    flask_session["quest_completed"] = True
                    completed, messages = complete_quest(squire_id, quest_id)

                    if completed:
                        for msg in messages:
                            flash(msg, "success")  # or use "quest" if you're styling categories

                        return jsonify({
                            "redirect": url_for("quest_select"),
                            "position": (x, y),
                            "message": message
                        })

                # Check for boss fight
                if event_type:
                    flask_session["mode"] = event_type
                    if event_type == "dungeon":
                        created = False
                        try:
                            # IMPORTANT: use the quest_id from the node, not a hardcoded default (39)
                            if not dungeon_exists(squire_id, quest_id):
                                rooms = generate_dungeon(squire_id, quest_id, size=10, path_length=50)
                                ok = insert_dungeon_to_db(rooms, squire_id, quest_id)
                                if not ok:
                                    current_app.logger.error("Dungeon insert failed for %s/%s", squire_id, quest_id)
                                    return jsonify({"action": "error", "message": "Dungeon creation failed"}), 500
                                created = True

                            db.commit()  # commit before telling client to navigate

                            # Optionally set session position for dungeon start
                            flask_session["dungeon_pos"] = [0, 0]
                            return jsonify({
                                "boss_fight": True,
                                "message": "You have reached the end of your Quest! Prepare for your doom, Squire!",
                                "position": (x, y),
                                "event": event_type
                            }), 200

                        except Exception:
                            db.rollback()
                            current_app.logger.exception("Error creating dungeon")
                            return jsonify({"action": "error", "message": "Server error creating dungeon"}), 500

                    return jsonify({
                        "boss_fight": True,
                        "message": "You have reached the end of your Quest! Prepare for your doom, Squire!",
                        "position": (x, y),
                        "event": event_type
                    }), 200



                if x == 0 and y == 0:
                    # Redirect to town
                    return jsonify({
                        "redirect": url_for("town.visit_town"),
                        "position": (x, y),
                        "message": message
                    })

                # Check for treasure
                chest = check_for_treasure_at_location(squire_id, x, y, quest_id, squire_quest_id)
                if chest:
                    logging.debug(f"Found a treasure chest at {x},{y}.")
                    flask_session["current_treasure_id"] = chest.id  # Store chest in session
                    event = "treasure"

                    # Record chest hint (only if new)
                    existing = db.query(ChestHint).filter_by(
                        squire_quest_id=squire_quest_id,
                        chest_x=x,
                        chest_y=y
                    ).first()

                    if not existing:
                        hint = ChestHint(
                            squire_quest_id=squire_quest_id,
                            chest_x=x,
                            chest_y=y
                        )
                        db.add(hint)
                        db.commit()
                    else:
                        logging.debug("👍 ChestHint already recorded for that location.")
                else:
                    # Random encounters
                    eligible_events = []

                    # 🏞️ NPC Encounter
                    if random.random() < 0.02:
                        eligible_events.append("npc")

                    if random.random() < 0.03:
                        eligible_events.append("npc_trader")

                    # 🧙‍♂️ Riddle Encounter
                    if random.random() < 0.02:
                        eligible_events.append("riddle")

                    # ⚔️ Combat
                    if random.random() < p:
                        eligible_events.append("enemy")

                    if random.random() < 0.02 and level > 3:
                        eligible_events.append("blacksmith")

                    if random.random() < 0.025:
                        eligible_events.append("clue")

                    if eligible_events:
                        event = random.choice(eligible_events)

                    # Process selected event
                    if event == "npc":
                        coords = (
                            db.query(
                                TreasureChest.x_coordinate,
                                TreasureChest.y_coordinate
                            )
                            .join(
                                Riddle,
                                TreasureChest.riddle_id == Riddle.id
                            )
                            .outerjoin(
                                SquireRiddleProgress,
                                and_(
                                    SquireRiddleProgress.riddle_id == Riddle.id,
                                    SquireRiddleProgress.squire_id == squire_id
                                )
                            )
                            .filter(
                                SquireRiddleProgress.riddle_id == None,           # not yet answered
                                Riddle.quest_id == quest_id,
                                TreasureChest.is_opened == False,
                                TreasureChest.squire_quest_id == squire_quest_id
                            )
                            .order_by(func.rand())  # MySQL's RAND()
                            .limit(1)
                            .first()
                        )

                        if coords:
                            chest_x, chest_y = coords
                            message = f"🌿 A wandering trader appears: 'There's a chest at ({chest_x},{chest_y}). I tried to open it but couldn't figure out the riddle. Good luck!'"
                            flask_session['npc_message'] = message
                            flask_session.modified = True
                            logging.debug(f"NPC Message Set: {message}")

                            # Add chest hint
                            db.add(ChestHint(
                                squire_quest_id=squire_quest_id,
                                chest_x=chest_x,
                                chest_y=chest_y
                            ))
                            db.commit()

                    elif event == "blacksmith":
                        return jsonify({"redirect": url_for("town.blacksmith"), "message": message})

                    elif event == "npc_trader":
                        return jsonify({"redirect": url_for("town.wandering_trader"), "message": message})

                    elif event == "clue":
                        # Manhattan distance to prefer "nearby"
                        dx = func.abs(TreasureChest.x_coordinate - x)
                        dy = func.abs(TreasureChest.y_coordinate - y)
                        dist = (dx + dy).label("dist")

                        # Find nearest unopened chest for THIS quest whose riddle isn't solved by this squire
                        # (Assumes: TreasureChest.riddle_id -> Riddle.id, and Riddle.quest_id marks the quest)
                        chest_row = (
                            db.query(TreasureChest, Riddle.hint, dist)
                              .join(Riddle, TreasureChest.riddle_id == Riddle.id)
                              .outerjoin(
                                  SquireRiddleProgress,
                                  and_(
                                      SquireRiddleProgress.riddle_id == Riddle.id,
                                      SquireRiddleProgress.squire_id == squire_id,
                                      SquireRiddleProgress.answered_correctly == True
                                  )
                              )
                              .filter(
                                  Riddle.quest_id == quest_id,
                                  TreasureChest.is_opened == False,        # unopened chest
                                  SquireRiddleProgress.id.is_(None)        # riddle not solved by this squire
                              )
                              .order_by(dist.asc(), func.rand())           # nearest first; break ties randomly
                              .first()
                        )

                        # Build the clue text
                        if not chest_row:
                            message = (
                                "🪧  You come across a sign along your path scrawled: "
                                "'Turn Back Now, Squire, or Face Your DOOOOOOOOOM.'"
                            )
                        else:
                            chest, hint, _ = chest_row
                            # Option 1: use the riddle hint
                            # message = f"🪧  A weathered sign whispers: '{hint}'."
                            # Option 2: give a directional clue toward the chest (spicier UX)
                            dx = chest.x_coordinate - x
                            dy = chest.y_coordinate - y
                            def step_dir(d, pos, neg):  # tiny helper
                                return pos if d > 0 else (neg if d < 0 else None)

                            dirs = [step_dir(dx, "East", "West"), step_dir(dy, "North", "South")]
                            dirs = [d for d in dirs if d]
                            arrow = " and ".join(dirs) if dirs else "right here"
                            message = f"🪧  A hand-drawn map points {arrow}. A faint note reads: '{hint}'."

                        flask_session['clue_message'] = message
                        flask_session.modified = True

                        return jsonify({
                            "redirect": url_for("town.clue"),
                            "message": message,
                            "position": (x, y),
                            "event": event,
                            "level": level
                        })


            # Non-directional or town-related commands
            else:
                # Keep current position as default
                message = f"You remain where you are, waiting for Godot."

                # Village/town visit command
                if direction == "V" or (x == 0 and y == 0):
                    # Reset position atomically in the database
                    db.query(Squire) \
                      .filter(Squire.id == squire_id) \
                      .update({
                          Squire.x_coordinate: 0,
                          Squire.y_coordinate: 0
                      })
                    db.commit()

                    # Update local variables to match
                    x, y = 0, 0

                    # Redirect to town
                    return jsonify({
                        "redirect": url_for("town.visit_town"),
                        "position": (x, y),
                        "message": message
                    })

                # Inventory command
                if direction == "I":
                    event = "inventory"
                    return jsonify({"redirect": url_for("town.inventory"), "message": message})

            # Generate updated map view
            game_map = get_viewport_map(db, squire_id, quest_id, 15)
            if not game_map:
                logging.error("❌ ERROR: get_viewport_map() returned None!")
                return jsonify({"error": "Failed to load the updated map."}), 500

            # Build and return response
            return jsonify({
                "map": game_map,
                "message": message,
                "position": (x, y),
                "event": event,
                "level": level
            })

        except Exception as e:
            db.rollback()  # Important: rollback transaction on error
            logging.exception(f"Error in /ajax_move: {e}")
            return jsonify({
                "error": "An error occurred while processing your movement.",
                "position": {"x": x, "y": y}
            }), 500
## riddles and treasure encounters here

@map_bp.route('/riddle_encounter', methods=['GET'])
def riddle_encounter():
    """Fetches a random unanswered riddle via ORM and displays it."""
    squire_id = flask_session.get("squire_id")
    quest_id  = flask_session.get("quest_id")
    if not squire_id:
        return redirect(url_for("login"))

    db = db_session()
    try:
        # 1) Query one random Riddle not yet in SquireRiddleProgress for this squire
        r = (
            db.query(Riddle)
              .outerjoin(
                  SquireRiddleProgress,
                  and_(
                      SquireRiddleProgress.riddle_id == Riddle.id,
                      SquireRiddleProgress.squire_id  == squire_id
                  )
              )
              .filter(
                  SquireRiddleProgress.riddle_id == None,
                  Riddle.quest_id               == quest_id
              )
              .order_by(func.rand())
              .first()
        )

        if not r:
            flask_session["riddle_message"] = "You've solved all riddles for this quest!"
            return redirect(url_for("map_view"))

        # Check if this is a new riddle or continuing with current one
        current_riddle = flask_session.get("current_riddle", {})
        riddle_session = get_riddle_session()

        # If it's a different riddle, reset session data
        if current_riddle.get("id") != r.id or riddle_session.get("riddle_id") != r.id:
            init_riddle_session(r.id)
            riddle_session = get_riddle_session()

        # Determine which hints to show
        show_hint         = ishint(db, squire_id)
        show_word_length  = iswordlengthhint(db, squire_id)
        show_word_count   = iswordcounthint(db, squire_id)

        # New hint types based on attempts
        show_first_letters = riddle_session.get("attempt_count", 0) >= 3

        # Store current riddle in session for later validation
        flask_session["current_riddle"] = {
            "id": r.id,
            "text": r.riddle_text,
            "answer": r.answer,
            "hint": r.hint,
            "word_length_hint": r.word_length_hint,
            "word_count": r.word_count,
            "show_hint": show_hint,
            "show_word_length": show_word_length,
            "show_word_count": show_word_count
        }

        # Calculate dynamic values for template
        attempt_count = riddle_session.get("attempt_count", 0)
        show_first_letters = attempt_count >= 3
        partial_words_found = riddle_session.get("partial_words_found", [])

        # Generate first letter hint if eligible
        first_letter_hint = None
        if show_first_letters:
            first_letter_hint = generate_first_letter_hint(r.answer)

        return render_template(
            "riddle.html",
            riddle=r,
            show_hint=show_hint,
            show_word_length=show_word_length,
            show_word_count=show_word_count,
            show_first_letters=show_first_letters,
            first_letter_hint=first_letter_hint,
            attempt_count=attempt_count,
            partial_words_found=partial_words_found
        )

    except Exception as e:
        logging.error(f"Error in riddle_encounter: {e}")
        return redirect(url_for("map_view"))
    finally:
        db.close()

@map_bp.route('/check_riddle', methods=['POST'])
def check_riddle():
    """Checks if the answer to the riddle is correct, using ORM."""
    squire_id    = flask_session.get("squire_id")
    quest_id     = flask_session.get("quest_id")
    current      = flask_session.get("current_riddle")
    source = request.form.get("source")

    if not squire_id or not current:
        logging.error(f"No active riddle found. Squire ID: {squire_id}, Session: {flask_session}")
        return jsonify(success=False, message="❌ No active riddle found!")

    logging.debug(f"Session contents: {flask_session}")
    logging.debug(f"Current riddle in session: {current}")
    riddle_id = current["id"]

    user_answer    = request.form.get("answer", "").strip().lower()
    correct_answer = current["answer"].strip().lower()

    riddle_session = get_riddle_session()

    # Increment attempt count
    riddle_session["attempt_count"] += 1
    riddle_session["all_attempts"].append(user_answer)

    if "all_attempts" not in riddle_session:
        riddle_session["all_attempts"] = []
        riddle_session["all_attempts"].append(user_answer)

    db = db_session()
    try:
        if user_answer == correct_answer:

            new_attempt = update_squire_question_attempt(db, squire_id, riddle_id, 'fill_in_blank', True, quest_id)

            # 1) Record in squire_riddle_progress
            progress = SquireRiddleProgress(
                squire_id=squire_id,
                riddle_id=riddle_id,
                quest_id=quest_id,
                answered_correctly=True
            )
            db.add(progress)

            # 2) Upsert in squire_questions
            sq = (
                db.query(SquireQuestion)
                  .filter_by(
                      squire_id=squire_id,
                      question_id=riddle_id,
                      question_type='riddle'
                  )
                  .one_or_none()
            )
            if not sq:
                update_squire_question(db, squire_id, riddle_id, 'riddle', True)
            else:
                sq.answered_correctly = True

            try:

                db.commit()
            except Exception as e:
                logging.error(f"Error committing for FITB question {e}")

            # 3) Calculate and award the special item
            special_item = calculate_riddle_reward(squire_id, riddle_id)

            # Clear session data since riddle is solved
            attempt_count = riddle_session["attempt_count"]
            clear_riddle_session()

            # 4) Notify the team
            toast = f"{flask_session['squire_name']} solved a riddle and received {special_item}."
            add_team_message(flask_session['team_id'], toast)
            try:

                db.commit()
            except Exception as e:
                logging.error(f"Error committing for FITB question {e}")

            flask_session.pop("current_riddle", None)
            if source == "dungeon":
                flask_session["combat_result"] = (
                    f"✅ Correct! A {special_item} appears in your inventory."
                )
                return redirect(url_for("dungeon.dungeon_map"))

            return jsonify(
                success=True,
                message=f"🎉 Correct! The wizard nods in approval and grants you {special_item}"
            )
        else:
            new_attempt = update_squire_question_attempt(db, squire_id, riddle_id, 'fill_in_blank', False, quest_id)
            # Check for partial matches in multi-word answers
            partial_result = check_partial_match(user_answer, correct_answer)
            first_letter_hint = ''

            # Update partial words found in session
            current_partial = riddle_session.get("partial_words_found", [])

            # Add newly found words
            for word_index, word in partial_result['found_words']:
                if word not in current_partial:
                    current_partial.append(word)

            riddle_session["partial_words_found"] = current_partial

            # Update session
            flask_session["riddle_attempts"] = riddle_session
            attempt_count = riddle_session["attempt_count"]
            flask_session.modified = True

            # Prepare feedback message
            feedback_parts = []

            if partial_result['found_count'] > 0:
                feedback_parts.append(f"You got {partial_result['found_count']} out of {partial_result['total_words']} words correct!")

                if len(current_partial) > 0:
                    feedback_parts.append(f"Words you've found so far: {', '.join(current_partial)}")

            if riddle_session["attempt_count"] >= 3:
                feedback_parts.append("The Wizard sets fire to the riddle, revealing the first letter of each word in the riddle.")
                first_letter_hint = generate_first_letter_hint(correct_answer)

            feedback_parts.append(f"Attempts: {riddle_session['attempt_count']}")

            flask_session["riddle_feedback"] = " | ".join(feedback_parts)

            if source == "dungeon":
                flask_session["combat_result"] = (
                    f"❌ Incorrect!"
                )
                return redirect(url_for("dungeon.dungeon_map"))

            # at the end of the “incorrect” branch in check_riddle
            return jsonify(
                success=False,
                message="❌ Incorrect! Try again.",
                partial_words_found=riddle_session["partial_words_found"],
                show_first_letters=attempt_count >= 3,
                first_letter_hint=first_letter_hint,
                attempt_count=attempt_count
            )


    except Exception as e:
        db.rollback()
        logging.error(f"Error in check_riddle: {e}")
        return jsonify(success=False, message="❌ An error occurred while checking your answer.")
    finally:
        db.close()

@map_bp.route('/treasure_encounter', methods=['GET'])
def treasure_encounter():
    """Handles the treasure chest encounter and displays the riddle."""
    squire_id = flask_session.get("squire_id")
    if not squire_id:
        return redirect(url_for("login"))

    # Ensure we have a chest selected
    if "current_treasure_id" not in flask_session:
        flask_session["treasure_message"] = "No treasure found at this location."
        return redirect(url_for("map_view"))

    chest_id = flask_session["current_treasure_id"]
    db = db_session()
    try:
        # 1) Load the unopened chest by ID
        chest = (
            db.query(TreasureChest)
              .filter(
                  TreasureChest.id == chest_id,
                  TreasureChest.is_opened == False
              )
              .one_or_none()
        )
        if not chest:
            flask_session["treasure_message"] = "No unopened treasure chests remain."
            return redirect(url_for("map_view"))

        # 2) Load its riddle
        riddle = db.query(Riddle).get(chest.riddle_id)
        if not riddle:
            flask_session["treasure_message"] = "No riddle found for this chest."
            return redirect(url_for("map_view"))

        # 3) Determine whether to show hint
        show_hint    = ishint(db, squire_id)
        return_hint  = riddle.hint if show_hint else None

        # 4) Update session with full treasure + riddle details
        flask_session["current_treasure"] = {
            "id":               chest.id,
            "riddle_id":        chest.riddle_id,
            "gold_reward":      chest.gold_reward,
            "xp_reward":        chest.xp_reward,
            "food_reward":      chest.food_reward,
            "special_item":     chest.special_item,
            "riddle_text":      riddle.riddle_text,
            "answer":           riddle.answer,
            "hint":             return_hint,
            "difficulty":       riddle.difficulty
        }

        # 5) Render it
        return render_template(
            "treasure.html",
            chest=flask_session["current_treasure"],
            response={}
        )
    finally:
        db.close()


@map_bp.route('/check_treasure', methods=['POST'])
def check_treasure():
    """Checks if the answer to the treasure riddle is correct, using ORM."""
    squire_id = flask_session.get("squire_id")
    quest_id  = flask_session.get("quest_id")
    chest_id   = flask_session.get("current_treasure_id")

    if not squire_id or not chest_id:
        return jsonify(success=False, message="❌ No active chest found!")

    db = db_session()
    chest = db.query(TreasureChest).get(chest_id)
    riddle = db.query(Riddle).get(chest.riddle_id)
    user_answer    = request.form.get("answer", "").strip().lower()

    logging.debug(f"{chest} {riddle} {user_answer}")

    current = {
        "id": chest.id,
        "riddle_id": riddle.id,
        "gold_reward": chest.gold_reward,
        "xp_reward": chest.xp_reward,
        "food_reward": chest.food_reward,
        "special_item": chest.special_item,
        "riddle_text": riddle.riddle_text,
        "answer": riddle.answer,
        "hint": riddle.hint,
        "difficulty": riddle.difficulty
    }


    correct_answer = current["answer"].strip().lower()
    logging.debug(f"{correct_answer}")


    try:
        if user_answer == correct_answer:
            chest_id     = current["id"]
            riddle_id    = current["riddle_id"]
            gold_reward  = current.get("gold_reward", 0)
            xp_reward    = current.get("xp_reward", 0)
            food_reward  = current.get("food_reward", 0)
            special_item = current.get("special_item")
            difficulty   = current.get("difficulty", "Easy")

            # 1) Record progress: riddle + question
            db.add(SquireRiddleProgress(
                squire_id          = squire_id,
                riddle_id          = riddle_id,
                quest_id           = quest_id,
                answered_correctly = True
            ))
            sq = (
                db.query(SquireQuestion)
                  .filter_by(
                      squire_id=squire_id,
                      question_id=riddle_id,
                      question_type='riddle'
                  )
                  .one_or_none()
            )
            if not sq:
                db.add(SquireQuestion(
                    squire_id          = squire_id,
                    question_id        = riddle_id,
                    question_type      = 'riddle',
                    answered_correctly = True
                ))
            else:
                sq.answered_correctly = True

            # 2) Award gold
            team = db.query(Team).get(db.query(Squire).get(squire_id).team_id)
            if gold_reward:
                team.gold += gold_reward
                team.reputation += 2

            # 3) Award XP
            squire = db.query(Squire).get(squire_id)
            if xp_reward:
                squire.experience_points += xp_reward

            # 4) Award food
            if food_reward:
                db.add(Inventory(
                    squire_id       = squire_id,
                    item_name       = "Magic Pizza",
                    description     = "Restores hunger",
                    uses_remaining  = food_reward,
                    item_type       = "food"
                ))

            # 5) Award special item
            if special_item:
                uses_map = {"Easy": 10, "Medium": 25, "Hard": 50}
                uses_remain = uses_map.get(difficulty, 10)
                db.add(Inventory(
                    squire_id       = squire_id,
                    item_name       = special_item,
                    description     = "A special item that affects gameplay",
                    uses_remaining  = uses_remain,
                    item_type       = "gear"
                ))

            # 6) Mark chest opened
            chest = db.query(TreasureChest).get(chest_id)
            chest.is_opened = True

            # 7) Commit all changes
            new_attempt = SquireQuestionAttempt(
                squire_id=squire_id,
                question_id=riddle_id,
                question_type='fill_in_blank',  # must match one of the ENUM values
                answered_correctly=True,
                quest_id=quest_id
                )

            try:
                db.add(new_attempt)
                db.commit()
            except Exception as e:
                logging.error(f"Error committing for FITB question {e}")

            # 8) Notify the team
            toast_parts = []
            if gold_reward:  toast_parts.append(f"{gold_reward} bitcoin")
            if xp_reward:    toast_parts.append(f"{xp_reward} XP")
            if food_reward:  toast_parts.append(f"{food_reward} food")
            if special_item: toast_parts.append(special_item)
            toast = (
                f"{flask_session['squire_name']} solved a riddle "
                f"and received {', '.join(toast_parts)}."
            )
            add_team_message(flask_session['team_id'], toast)
            db.commit()

            flask_session.pop("current_treasure", None)
            reward_msgs = []
            if gold_reward:  reward_msgs.append(f"💰 You found {gold_reward} bitcoin!")
            if xp_reward:    reward_msgs.append(f"🎖️ You gained {xp_reward} XP!")
            if food_reward:  reward_msgs.append(f"🍖 You found {food_reward} special food items!")
            if special_item: reward_msgs.append(f"🛡️ You discovered a rare item: {special_item}!")

            return jsonify(
                success=True,
                message="✅ Correct! The chest unlocks! " + " ".join(reward_msgs)
            )
        else:
            riddle_id    = current["riddle_id"]
            new_attempt = SquireQuestionAttempt(
                squire_id=squire_id,
                question_id=riddle_id,
                question_type='fill_in_blank',  # must match one of the ENUM values
                answered_correctly=False,
                quest_id=quest_id
                )

            try:
                db.add(new_attempt)
                db.commit()
            except Exception as e:
                logging.error(f"Error committing for FITB question {e}")

            return jsonify(
                success=False,
                message="❌ Incorrect! The chest remains locked. Try again later."
            )
    except Exception as e:
        db.rollback()
        logging.debug(f"Treasure Evaluation error {e}")
        return jsonify(success=False, message="❌ An error occurred."), 500
    finally:
        db.close()
