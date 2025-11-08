from db import Squire, Course, Team, engine, db_session, Team, TravelHistory, Quest, SquireQuestion, SquireRiddleProgress, Riddle, Enemy, Inventory, WizardItem, Job, MapFeature, MultipleChoiceQuestion, TrueFalseQuestion, ShopItem, SquireQuestStatus, TeamMessage, TreasureChest, XpThreshold, ChestHint
from flask import session as flask_session
from sqlalchemy import or_, func, and_, asc, not_, desc
from sqlalchemy.dialects.mysql import insert

from utils.shared import can_enter_tile
from utils.shared import update_squire_progress

import logging


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

        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logging.warning(f"Update player position generated an error on squire: {e}")

        # 5) Log travel history
        stmt = insert(TravelHistory).values(
            squire_id=squire_id,
            x_coordinate=x,
            y_coordinate=y
        ).prefix_with("IGNORE")  # Optional: skip if exists

        db.execute(stmt)
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logging.warning(f"Update player position generated an error on travelhistory: {e}")

        message = f"🌿 You travel unhindered towards the {direction}."
        return x, y, message

    finally:
        db.close()
