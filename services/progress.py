from db import Squire, Course, Team, engine, db_session, Team, TravelHistory, Quest, SquireQuestion, SquireRiddleProgress, Riddle, Enemy, Inventory, WizardItem, Job, MapFeature, MultipleChoiceQuestion, TrueFalseQuestion, ShopItem, SquireQuestStatus, TeamMessage, TreasureChest, XpThreshold, ChestHint
from flask import session as flask_session
from sqlalchemy import or_, func, and_, asc, not_, desc
from sqlalchemy.dialects.mysql import insert

import logging

from utils.shared import get_squire_stats
from utils.shared import check_quest_completion
from utils.shared import complete_quest
from utils.shared import get_random_riddle
from utils.shared import check_riddle_answer
from utils.shared import get_active_quests
from utils.shared import chooseq
from utils.shared import get_riddles_for_quest
from utils.shared import get_inventory
from utils.shared import visit_shop
from utils.shared import consume_food
from utils.shared import get_hunger_bar
from utils.shared import check_for_treasure
from utils.shared import open_treasure_chest
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

# travel
def log_travel_history(db_session, squire_id, x, y):
    """Logs the player's movement in the travel_history table using ORM."""
    # Avoid duplicate entries by checking for existing record
    existing = db_session.query(TravelHistory).filter_by(
        squire_id = squire_id,
        x_coordinate = x,
        y_coordinate = y
    ).first()
    if not existing:
        record = TravelHistory(
            squire_id    = squire_id,
            x_coordinate = x,
            y_coordinate = y
        )
        db_session.add(record)
        db_session.commit()

def can_enter_tile(db_session, squire_id, new_x, new_y):
    """
    Returns True if the squire can enter the tile at (new_x, new_y), based on terrain and inventory.
    """
    # Look up terrain at the specified coordinates
    mf = (
        db_session.query(MapFeature)
        .filter_by(
            squire_id=squire_id,
            x_coordinate=new_x,
            y_coordinate=new_y
        )
        .first()
    )
    if mf:
        terrain = mf.terrain_type
        if terrain == 'mountain':
            # Require boots
            return (
                db_session.query(Inventory)
                .filter(
                    Inventory.squire_id == squire_id,
                    Inventory.item_name.ilike('%Boots%')
                )
                .count() > 0
            )
        if terrain == 'river':
            # Require boat
            return (
                db_session.query(Inventory)
                .filter(
                    Inventory.squire_id == squire_id,
                    Inventory.item_name.ilike('%Boat%')
                )
                .count() > 0
            )
    # Default: allow entry
    return True

def update_squire_progress(squire_id: int, xp_gain: int, gold_gain: int) -> list[str]:
    """
    Adds XP and gold to the squire (and their team), then checks for level-up.
    Returns a list of messages indicating what happened (e.g., level-up).
    """
    messages = []
    db = db_session()
    try:
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return messages

        # Update XP
        squire.experience_points = (squire.experience_points or 0) + xp_gain
        # Update Team gold
        team = db.query(Team).get(squire.team_id)
        if team:
            team.gold = (team.gold or 0) + gold_gain
            team.reputation += 1

        db.commit()

        # Level-up check
        new_level = check_for_level_up(squire_id,db)
        if new_level is not None:
            flask_session["leveled_up"] = True
            flask_session["new_level"] = new_level

    finally:
        db.close()

def check_for_level_up(squire_id: int, db) -> int | None:
    squire = db.query(Squire).get(squire_id)
    xp = squire.experience_points or 0
    current_level = squire.level

    thresholds = ( db.query(XpThreshold)
        .order_by(XpThreshold.level.asc())
        .all()
        )

    for threshold in thresholds:
        if current_level < threshold.level and xp >= threshold.min:
            squire.level = threshold.level
            db.commit()
            return threshold.level
    return None

def update_player_position(db, squire_id: int, direction: str):
    """
    Updates the player's coordinates based on movement direction,
    records travel history, and returns (new_x, new_y, message).
    """
    try:
        # 1) Load current position
        squire = db.query(Squire).get(squire_id)
        if not squire:
            logging.error("❌ ERROR: Player not found in update_player_position!")
            return None

        x_orig, y_orig = squire.x_coordinate, squire.y_coordinate

        # 2) Compute new coords
        if direction == "N":
            x, y = x_orig, y_orig + 1
        elif direction == "S":
            x, y = x_orig, y_orig - 1
        elif direction == "E":
            x, y = x_orig + 1, y_orig
        elif direction == "W":
            x, y = x_orig - 1, y_orig
        elif direction == "V":
            x, y = 0, 0
        else:
            x, y = x_orig, y_orig

        logging.debug(f"Moving {direction} from ({x_orig},{y_orig}) → ({x},{y})")

        # 3) Check tile entry permission
        if not can_enter_tile(db, squire_id, x, y):
            message = "❌ Sorry, but you have to take the long way around that map feature."
            return x_orig, y_orig, message

        # 4) Update squire position
        squire.x_coordinate = x
        squire.y_coordinate = y
        db.commit()

        # 5) Log travel history
        stmt = insert(TravelHistory).values(
            squire_id=squire_id,
            x_coordinate=x,
            y_coordinate=y
        ).prefix_with("IGNORE")  # Optional: skip if exists

        db.execute(stmt)
        db.commit()

        message = f"🌿 You travel unhindered towards the {direction}."
        return x, y, message

    finally:
        db.close()
