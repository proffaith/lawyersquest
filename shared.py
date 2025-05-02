import random
import logging
import pymysql
import os
import decimal
import configparser
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from dotenv import load_dotenv
from db import Squire, Course, Team, engine, db_session, Team, TravelHistory, Quest, SquireQuestion, SquireRiddleProgress, Riddle, Enemy, Inventory, WizardItem, Job, MapFeature, MultipleChoiceQuestion, TrueFalseQuestion, ShopItem, SquireQuestStatus, TeamMessage, TreasureChest, XpThreshold
from sqlalchemy import or_, func, and_, asc, not_
from sqlalchemy.dialects.mysql import insert
from decimal import Decimal


# Load environment variables
load_dotenv()

# ************************************
# This Python Script created 3/4/25 TF
# This script contains consolidated functions for use by the game play
# ************************************


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


def get_viewport_map(db, squire_id: int, quest_id: int, viewport_size: int = 15) -> str:
    """
    Builds a little HTML table (15×15 by default) around the player’s position,
    showing visited dots, terrain icons, and the player marker.
    """
    try:
        # 1) All visited coords
        visited = {
            (h.x_coordinate, h.y_coordinate)
            for h in db.query(TravelHistory)
                       .filter_by(squire_id=squire_id)
                       .all()
        }

        # 2) Player pos
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return "<p>⚠️ Error: Player position not found.</p>"
        x, y = squire.x_coordinate, squire.y_coordinate

        # 3) All terrain features for this squire
        features = db.query(MapFeature).filter_by(squire_id=squire_id).all()
        feature_map = {
            (f.x_coordinate, f.y_coordinate): f.terrain_type
            for f in features
        }

        # 4) Compute bounds
        half = viewport_size // 2
        x_min, x_max = x - half, x + half
        y_min, y_max = y - half, y + half

        # 5) Build HTML
        out = ['<table class="game-map" style="border-collapse: collapse;">']
        for ry in range(y_max, y_min - 1, -1):
            out.append("<tr>")
            for cx in range(x_min, x_max + 1):
                if (cx, ry) == (x, y):
                    char = "📍"
                elif (cx, ry) == (0, 0):
                    char = "🏰"
                elif (cx, ry) == (40, 40):
                    char = "🏰"
                elif (cx, ry) in feature_map:
                    t = feature_map[(cx, ry)]
                    char = {"forest":"🌲","mountain":"🏔️","river":"🌊"}.get(t, "⬜")
                elif (cx, ry) in visited:
                    char = "•"
                else:
                    char = "⬜"
                out.append(
                    f'<td style="width:30px;height:30px;text-align:center;'
                    f'border:1px solid #333">{char}</td>'
                )
            out.append("</tr>")
        out.append("</table>")
        out.append(
            """<p>📍=You | •=Visited | 🏰=Home | 🌲=Forest | 🏔️=Mountain | 🌊=River</p>"""
        )
        return "\n".join(out)

    finally:
        db.close()

def display_travel_map(squire_id: int, quest_id: int) -> str:
    """
    Generates an HTML-based map showing forests, visited locations, and the player,
    using ORM queries instead of raw SQL.
    """
    db = db_session()
    try:
        # 1) Gather visited coordinates
        visited_rows = (
            db.query(TravelHistory.x_coordinate, TravelHistory.y_coordinate)
              .filter(TravelHistory.squire_id == squire_id)
              .all()
        )
        visited = {(r.x_coordinate, r.y_coordinate) for r in visited_rows}

        # 2) Load player’s current position
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return "<p>⚠️ Error: Player position not found.</p>"
        x, y = squire.x_coordinate, squire.y_coordinate

        # 3) Fetch all terrain features for this squire
        feature_objs = (
            db.query(MapFeature)
              .filter(MapFeature.squire_id == squire_id)
              .all()
        )
        feature_map = {
            (f.x_coordinate, f.y_coordinate): f.terrain_type
            for f in feature_objs
        }

    finally:
        db.close()

    # 4) Determine dynamic grid bounds
    all_points = visited | set(feature_map.keys()) | {(x, y), (0, 0)}
    if all_points:
        min_x = min(px for px, _ in all_points)
        max_x = max(px for px, _ in all_points)
        min_y = min(py for _, py in all_points)
        max_y = max(py for _, py in all_points)
    else:
        # fallback grid
        min_x, max_x, min_y, max_y = -4, 4, -4, 4

    # 5) Build HTML table
    html = ['<table class="game-map" style="border-collapse: collapse;">']
    for row in range(max_y, min_y - 1, -1):
        html.append("<tr>")
        for col in range(min_x, max_x + 1):
            if (col, row) == (x, y):
                char = "📍"
            elif (col, row) == (0, 0):
                char = "🏰"
            elif (col, row) in feature_map:
                terr = feature_map[(col, row)]
                char = {
                    "forest":   "🌲",
                    "mountain": "🏔️",
                    "river":    "🌊"
                }.get(terr, "⬜")
            elif (col, row) in visited:
                char = "•"
            else:
                char = "⬜"

            html.append(
                f'<td style="width:30px;height:30px;text-align:center;'
                f'border:1px solid #333">{char}</td>'
            )
        html.append("</tr>")
    html.append("</table>")

    # 6) Legend
    html.append("""
    <p>📍 = You &nbsp; | &nbsp; • = Visited &nbsp; | &nbsp; 🏰 = Home Village
    &nbsp; | &nbsp; 🌲 = Forest &nbsp; | &nbsp; 🏔️ = Mountain &nbsp; | &nbsp; ⬜ = Unexplored</p>
    """)

    return "\n".join(html)


# TREASURE! AAAARRRRRRRRRRRRR.
def ishint(db_session, squire_id):
    """Returns True if the squire has any item with a name containing 'Scroll' (e.g., hint scrolls)"""
    return (
        db_session.query(func.count(Inventory.id))
        .filter(
            Inventory.squire_id == squire_id,
            Inventory.item_name.ilike('%banishment%')  # Case-insensitive match
        )
        .scalar() > 0
    )


def iswordlengthhint(db_session, squire_id):
    """Returns True if the squire can see word length hints"""
    return (
        db_session.query(func.count(Inventory.id))
                  .filter(
                      Inventory.squire_id == squire_id,
                      Inventory.item_name == 'four-leaf clover'
                  )
                  .scalar() > 0
    )


def iswordcounthint(db_session, squire_id):
    """Returns True if the squire can see word count hints"""
    return (
        db_session.query(func.count(Inventory.id))
                  .filter(
                      Inventory.squire_id == squire_id,
                      Inventory.item_name.ilike('%Keys to the Kingdom%')
                  )
                  .scalar() > 0
    )


def check_for_treasure_at_location(
    squire_id: int,
    x: int,
    y: int,
    quest_id: int,
    squire_quest_id: int
) -> TreasureChest | None:
    """
    Returns the unopened TreasureChest at (x,y) for this squire & quest,
    only if the associated riddle has not yet been solved by this squire.
    """
    db = db_session()
    try:
        chest = (
            db.query(TreasureChest)
              # join to Riddle to filter by quest
              .join(Riddle, TreasureChest.riddle_id == Riddle.id)
              # left‐outer join to progress so we can require “no progress row”
              .outerjoin(
                  SquireRiddleProgress,
                  and_(
                      SquireRiddleProgress.riddle_id == Riddle.id,
                      SquireRiddleProgress.squire_id  == squire_id
                  )
              )
              .filter(
                  Riddle.quest_id             == quest_id,
                  TreasureChest.x_coordinate  == x,
                  TreasureChest.y_coordinate  == y,
                  TreasureChest.squire_quest_id == squire_quest_id,
                  SquireRiddleProgress.riddle_id == None
              )
              .first()
        )
        return chest
    finally:
        db.close()

def check_for_treasure(squire_id: int, quest_id: int):
    """
    Checks if a treasure chest exists at the player's current location
    for the given quest, and returns the ORM TreasureChest instance or None.
    """
    db = db_session()
    try:
        # 1) Retrieve player's current position
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return None
        x, y = squire.x_coordinate, squire.y_coordinate

        # 2) Look for an unopened chest whose riddle belongs to this quest
        chest = (
            db.query(TreasureChest)
              .join(Riddle, TreasureChest.riddle_id == Riddle.id)
              .outerjoin(
                  SquireRiddleProgress,
                  and_(
                      SquireRiddleProgress.riddle_id == Riddle.id,
                      SquireRiddleProgress.squire_id  == squire_id
                  )
              )
              .filter(
                  Riddle.quest_id              == quest_id,
                  TreasureChest.x_coordinate   == x,
                  TreasureChest.y_coordinate   == y,
                  TreasureChest.squire_quest_id == quest_id,
                  SquireRiddleProgress.riddle_id == None
              )
              .first()
        )
        return chest
    finally:
        db.close()

# Example usage:
# chest = check_for_treasure(2, 15)
# if chest:
#     print(f"Found chest at ({chest.x_coordinate}, {chest.y_coordinate}) with riddle ID {chest.riddle_id}")
# else:
#     print("No chest here.")

def open_treasure_chest(squire_id: int, chest_id: int) -> str:
    """
    Handles the treasure chest interaction in a console flow, using SQLAlchemy ORM.
    Returns a summary message indicating rewards or failure.
    """
    db = db_session()
    try:
        # Load chest and riddle
        chest = db.query(TreasureChest).get(chest_id)
        if not chest:
            return "❌ Chest not found."

        riddle = db.query(Riddle).get(chest.riddle_id)
        if not riddle:
            return "❌ Riddle not found for this chest."

        # Display riddle
        print("\n🎁 You have discovered a Treasure Chest!")
        print("🔒 The chest is locked... Solve the riddle to open it!")
        print(f"\n📜 Riddle: {riddle.riddle_text}")

        # Check for lexiconis hint item
        magic_count = (
            db.query(Inventory)
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_name.ilike("%lexiconis%")
              )
              .count()
        )
        if magic_count > 0:
            print(f"💡 Clue: {riddle.word_length_hint} (Number of letters in each word)")

        # Prompt for answer
        answer = input("Enter your answer: ").strip().lower()
        correct = (answer == riddle.answer.strip().lower())

        if not correct:
            return "❌ Incorrect! The chest remains locked. Try again later."

        # Begin rewards
        msgs = ["✅ Correct! The chest unlocks, revealing its treasures!"]

        # 1) Mark progress
        progress = SquireRiddleProgress(
            squire_id=squire_id,
            riddle_id=riddle.id,
            quest_id=riddle.quest_id,
            answered_correctly=True
        )
        db.add(progress)
        # Also upsert SquireQuestion
        sq = db.query(SquireQuestion).filter_by(
            squire_id=squire_id,
            question_id=riddle.id,
            question_type='riddle'
        ).one_or_none()
        if not sq:
            db.add(SquireQuestion(
                squire_id=squire_id,
                question_id=riddle.id,
                question_type='riddle',
                answered_correctly=True
            ))
        else:
            sq.answered_correctly = True

        # 2) Award gold
        team = db.query(Team).get(db.query(Squire).get(squire_id).team_id)
        if chest.gold_reward > 0:
            team.gold += chest.gold_reward
            team.reputation += 2
            msgs.append(f"💰 You found {chest.gold_reward} bitcoin!")

        # 3) Award XP
        squire = db.query(Squire).get(squire_id)
        if chest.xp_reward > 0:
            squire.experience_points += chest.xp_reward
            msgs.append(f"🎖️ You gained {chest.xp_reward} XP!")

        # 4) Award food
        if chest.food_reward > 0:
            inv_food = Inventory(
                squire_id=squire_id,
                item_name="Magic Pizza",
                description="Restores hunger",
                uses_remaining=chest.food_reward,
                item_type="food"
            )
            db.add(inv_food)
            msgs.append(f"🍖 You found {chest.food_reward} special food items!")

        # 5) Award special gear
        if chest.special_item:
            uses_map = {"Easy": 10, "Medium": 25, "Hard": 50}
            uses = uses_map.get(riddle.difficulty, 10)
            inv_gear = Inventory(
                squire_id=squire_id,
                item_name=chest.special_item,
                description="A special item that affects gameplay",
                uses_remaining=uses,
                item_type="gear"
            )
            db.add(inv_gear)
            msgs.append(f"🛡️ You discovered a rare item: {chest.special_item}!")

        # 6) Mark chest opened
        chest.is_opened = True

        db.commit()
        return " ".join(msgs)

    except Exception as e:
        db.rollback()
        logging.error(f"Error in open_treasure_chest: {e}")
        return "❌ An error occurred while opening the treasure."
    finally:
        db.close()

# Example invocation:
# message = open_treasure_chest(squire_id=2, chest_id=5)
# print(message)

def calculate_riddle_reward(squire_id: int, riddle_id: int) -> str:
    """
    Selects a random wizard item appropriate to the squire's level,
    adjusts its uses by riddle difficulty, awards it in Inventory, and
    returns the item name (or a default string if none).
    """
    db = db_session()
    try:
        # 1) Get the squire and their level
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return "nothing because knowledge is its own reward."
        level = squire.level
        logging.debug(f"Calc Riddle Reward: level={level}")

        # 2) Pick a random WizardItem up to that level
        item = (
            db.query(WizardItem)
              .filter(WizardItem.min_level <= level)
              .order_by(func.random())
              .first()
        )
        if not item:
            return "nothing because knowledge is its own reward."

        special_item = item.item_name
        uses = item.uses
        logging.debug(f"Calc Riddle Reward: picked {special_item} with base uses {uses}")

        # 3) Adjust uses based on riddle difficulty
        r = db.query(Riddle).get(riddle_id)
        diff = r.difficulty if r else "Easy"
        logging.debug(f"Calc Riddle Reward: difficulty={diff}")

        if diff == "Medium":
            uses += 10
        elif diff == "Hard":
            uses += 25

        # 4) Insert into Inventory
        inv = Inventory(
            squire_id       = squire_id,
            item_name       = special_item,
            description     = "magical item affecting game play",
            uses_remaining  = uses,
            item_type       = "gear"
        )
        db.add(inv)
        db.commit()

        return special_item

    except Exception as e:
        db.rollback()
        logging.error(f"Error in calculate_riddle_reward: {e}")
        return "nothing because knowledge is its own reward."
    finally:
        db.close()



# battle of the beasties

def flee_safely(e,p, hit_chance):

    e = int(e)
    p = int(p)

    if p == 0:
        p = 1

    damage_probability = (e / p) * ((100 - hit_chance) / 100 )
    damage_probability = min(max(damage_probability,0),1)

    logging.debug(f"Flee Safely damage probability: {damage_probability}")

    if random.randint(0, 1) < damage_probability:
        return False
    else:
        return True

def calc_flee_safely(e, p, hit_chance):
    e = int(e)
    p = int(p)

    if p == 0:
        p = 1

    damage_probability = round(((e / p) * ((100 - hit_chance) / 100)) * 100)
    damage_probability = min(max(damage_probability, 0), 100)

    return damage_probability

def calculate_enemy_encounter_probability(
    squire_id: int,
    quest_id: int,  # unused, kept for signature compatibility
    current_x: int,
    current_y: int,
    squire_quest_id: int,
    proximity: int = 2
) -> float:
    """
    Calculates the probability of encountering an enemy based on nearby features,
    using SQLAlchemy ORM instead of raw SQL.
    """
    db = db_session()
    try:
        base_probability = 0.05

        # 1) Count nearby terrain features by type
        terrain_counts = (
            db.query(
                MapFeature.terrain_type,
                func.count().label("count")
            )
            .filter(
                func.abs(MapFeature.x_coordinate - current_x) <= proximity,
                func.abs(MapFeature.y_coordinate - current_y) <= proximity,
                MapFeature.squire_id == squire_id
            )
            .group_by(MapFeature.terrain_type)
            .all()
        )

        # 2) Adjust based on feature type
        for terrain, count in terrain_counts:
            if terrain == "forest":
                base_probability += 0.02 * count
            elif terrain == "mountain":
                base_probability += 0.03 * count
            elif terrain == "river":
                base_probability += 0.04 * count

        # 3) Count nearby unopened treasure chests
        chest_count = (
            db.query(func.count(TreasureChest.id))
            .filter(
                func.abs(TreasureChest.x_coordinate - current_x) <= proximity,
                func.abs(TreasureChest.y_coordinate - current_y) <= proximity,
                TreasureChest.squire_quest_id == squire_quest_id,
                TreasureChest.is_opened == False
            )
            .scalar()
        )

        if chest_count:
            base_probability += 0.04 * chest_count

        # 4) Clamp probability
        probability = min(max(base_probability, 0.0), 0.9)
        return probability

    finally:
        db.close()

# Example usage:
# prob = calculate_enemy_encounter_probability(2, 15, 10, 5, 7)
# print(f"Encounter chance: {prob:.2%}")

def calculate_hit_chance(squire_id: int, level: int) -> float:
    """
    Calculates hit chance based on the total number of True/False questions
    and riddles, and how many the squire has answered correctly.
    Returns a percentage capped at 95%.
    """
    db = db_session()
    try:
        # 1) Total T/F questions
        total_tf = db.query(func.count(TrueFalseQuestion.id)).scalar() or 0

        # 2) Total riddles
        total_r = db.query(func.count(Riddle.id)).scalar() or 0

        allqs = total_tf + total_r
        if allqs == 0:
            return 0.0  # no questions means no bonus

        # 3) Distinct correctly answered questions
        correct = (
            db.query(func.count(func.distinct(SquireQuestion.question_id)))
              .filter(
                  SquireQuestion.squire_id == squire_id,
                  SquireQuestion.answered_correctly == True
              )
              .scalar() or 0
        )

        # 4) Compute combat modifier
        combatmod = correct / allqs

        # 5) Base hit chance: 2% per level plus combatmod
        base_hit = (level * 2) + combatmod

        # 6) Cap at 95%
        return min(base_hit, 95.0)
    finally:
        db.close()

# Example usage:
# hit_chance = calculate_hit_chance(squire_id=2, level=3)
# print(f"Hit chance: {hit_chance:.2f}%")

def combat_mods(squire_id: int, enemy_name: str, level: int) -> int:
    """
    Calculates combat modifiers:
      - +1 per 'gear' item with uses remaining
      - +5 per 'special' item effective against the given enemy
      - +2 per player level
    """
    db = db_session()
    try:
        # 1) Count usable gear items
        base_mod = (
            db.query(func.count(Inventory.id))
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_type == 'gear',
                  Inventory.uses_remaining > 0
              )
              .scalar()
            or 0
        )

        # 2) Count special items effective against this enemy
        enemy_mod = (
            db.query(func.count(Inventory.id))
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_type == 'special',
                  Inventory.effective_against == enemy_name
              )
              .scalar()
            or 0
        )

        # 3) Level contribution
        level_mod = 2 * level

        total_mods = base_mod + (enemy_mod * 5) + level_mod
        logging.debug(f"combat_mods → squire={squire_id}, enemy={enemy_name}, "
                      f"gear={base_mod}, special={enemy_mod}, level={level_mod}, total={total_mods}")

        return total_mods

    finally:
        db.close()

# Example usage:
# mods = combat_mods(squire_id=2, enemy_name='Goblin', level=3)
# print(f"Total combat modifier: {mods}")

def hunger_mods(squire_id: int) -> int:
    """
    Returns the count of 'gold coin pouch' items for the squire,
    which modify the player's hunger level.
    """
    db = db_session()
    try:
        count = (
            db.query(func.count(Inventory.id))
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_name == 'gold coin pouch'
              )
              .scalar()
            or 0
        )
        logging.debug(f"hunger_mods → squire={squire_id}, count={count}")
        return count
    finally:
        db.close()

def degrade_gear(squire_id: int, weapon: str) -> bool:
    """
    Decrements uses of the specified weapon and all non-exempt gear,
    deleting any inventory rows whose uses drop below 1.
    """
    db = db_session()
    try:
        # 1) Degrade the specific weapon
        inv = (
            db.query(Inventory)
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_name == weapon
              )
              .order_by(Inventory.uses_remaining.asc())
              .first()
        )
        if inv:
            inv.uses_remaining -= 1
            if inv.uses_remaining < 1:
                db.delete(inv)
        db.commit()

        # 2) Degrade all regular gear (except the exempt list)
        exempt = ['Pen', 'Calculator', 'Law Book', 'Stamp']
        gear_items = (
            db.query(Inventory)
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_type == 'gear',
                  not_(Inventory.item_name.in_(exempt))
              )
              .all()
        )
        for g in gear_items:
            g.uses_remaining -= 1
            if g.uses_remaining < 1:
                db.delete(g)
        db.commit()
        logging.debug(f"degrade_gear → squire={squire_id}, weapon_degraded={bool(inv)}, gear_degraded={len(gear_items)}")
        return True
    except Exception as e:
        db.rollback()
        logging.error(f"Error in degrade_gear: {e}")
        return False
    finally:
        db.close()

def update_work_for_combat(squire_id: int) -> bool:
    """
    Resets the squire's work_sessions to zero before combat.
    Always returns False to indicate no further 'work' is allowed immediately.
    """
    db = db_session()
    try:
        squire = db.query(Squire).get(squire_id)
        if squire:
            squire.work_sessions = 0
            db.commit()
            logging.debug(f"update_work_for_combat → squire={squire_id}, work_sessions reset")
        return False
    except Exception as e:
        db.rollback()
        logging.error(f"Error in update_work_for_combat: {e}")
        return False
    finally:
        db.close()

def get_player_max_hunger(squire_id: int):
    """
    Returns:
      - max_hunger: total sum of food uses the squire has.
      - next_food: first available food Inventory instance or None.
    """
    db = db_session()
    try:
        max_hunger = (
            db.query(func.coalesce(func.sum(Inventory.uses_remaining), 0))
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_type == 'food'
              )
              .scalar()
        )

        next_food = (
            db.query(Inventory)
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_type == 'food',
                  Inventory.uses_remaining > 0
              )
              .first()
        )

        return max_hunger, next_food
    finally:
        db.close()

def mod_enemy_hunger(mod, enemy, forest, mountain):
    #calculates the max hunger of the enemy based on distance from village + terrain modifier
    emh = enemy

    #harder to defeat enemy in forests or mountains
    if forest == True:
        emh += 2
    elif mountain == True:
        emh +=3

    #harder to defeat enemy based on overall distance from village
    if 51 <= mod <= 150:
        emh += 1
    elif 151 <= mod <= 500:
        emh += 2
    elif 501 <= mod <= 1000:
        emh += 3
    elif mod > 1000:
        emh += 5

    return emh

def get_squire_stats(squire_id: int) -> tuple[int, int]:
    """
    Fetches the player's current XP and gold using ORM models.
    Returns (experience_points, gold).
    """
    db = db_session()
    try:
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return 0, 0
        team = db.query(Team).get(squire.team_id)
        xp = squire.experience_points or 0
        gold = team.gold if team else 0
        return xp, gold
    finally:
        db.close()

def check_for_level_up(squire_id: int) -> int | None:
    """
    Checks if the squire has enough XP to level up.
    Updates the level if thresholds are met.
    Returns the new level if leveled up, otherwise None.
    """
    db = db_session()
    try:
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return None

        # Fetch thresholds ordered by level ascending
        thresholds = db.query(XpThreshold).order_by(asc(XpThreshold.level)).all()
        new_level = squire.level
        for thr in thresholds:
            if squire.experience_points >= thr.min:
                new_level = thr.level
            else:
                break

        # Apply level up if needed
        if new_level > squire.level:
            squire.level = new_level
            db.commit()
            return new_level

        return None
    finally:
        db.close()

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
        new_level = check_for_level_up(squire_id)
        if new_level is not None:
            messages.append(f"🎉 Congratulations! You leveled up to Level {new_level}!")

        return messages
    finally:
        db.close()

# Example usage:
# xp, gold = get_squire_stats(2)
# level_up_msgs = update_squire_progress(2, xp_gain=20, gold_gain=50)
# if level_up_msgs:
#     for msg in level_up_msgs:
#         print(msg)


def get_inventory(squire_id: int):
    """
    Returns a list of inventory summaries for the given squire:
    each entry contains item_name, item_type, description,
    total uses_remaining, and count of stacks (effect).
    """
    db = db_session()
    try:
        results = (
            db.query(
                Inventory.item_name,
                Inventory.item_type,
                Inventory.description,
                func.sum(Inventory.uses_remaining).label("uses_remaining"),
                func.count().label("effect")
            )
            .filter(Inventory.squire_id == squire_id)
            .group_by(
                Inventory.item_name,
                Inventory.item_type,
                Inventory.description
            )
            .order_by(
                Inventory.item_type,
                Inventory.item_name
            )
            .all()
        )
        return results  # List of named tuples
    finally:
        db.close()

def get_hunger_bar(squire_id: int) -> str:
    """
    Generates a hunger bar displaying up to 8 segments:
      🟩 for available food uses and 🟥 for hunger.
    """
    db = db_session()
    try:
        total_uses = (
            db.query(func.coalesce(func.sum(Inventory.uses_remaining), 0))
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_type == 'food'
              )
              .scalar()
        )
        total_uses = int(total_uses)  # 🛡️ Ensure it's an int before min()
    finally:
        db.close()

    full_count = min(total_uses, 8)
    hunger_count = 8 - full_count
    hunger_bar = " ".join(["🟩"] * full_count + ["🟥"] * hunger_count)
    return hunger_bar


# Example usage:
# inv = get_inventory(2)
# for row in inv:
#     print(row)
# print(get_hunger_bar(2))


def check_quest_progress(squire_id: int, quest_id: int) -> tuple[int, int, float]:
    """
    Returns (answered_count, total_required, progress_percentage).
    """

    db = db_session()
    try:
        total_hard = (
            db.query(func.count(Riddle.id))
              .filter(
                  Riddle.quest_id == quest_id,
                  Riddle.difficulty == 'Hard'
              )
              .scalar() or 0
        )
        total_required = int(total_hard) + 6  # ✅ cast to int

        answered = (
            db.query(func.count(SquireRiddleProgress.id))
              .filter(
                  SquireRiddleProgress.squire_id == squire_id,
                  SquireRiddleProgress.quest_id == quest_id,
                  SquireRiddleProgress.answered_correctly == True
              )
              .scalar() or 0
        )
        answered = int(answered)  # ✅ just to be safe

        progress = float(answered / total_required * 100) if total_required else 0.0

        return answered, total_required, progress
    finally:
        db.close()


def display_progress_bar(percentage):
    """Generates a text-based progress bar."""
    percentage = float(percentage)  # ✨ Cast once, rule all
    bar_length = 20
    filled_length = int(bar_length * (percentage / 100))
    bar = "█" * filled_length + "-" * (bar_length - filled_length)
    return f"[{bar}] {percentage:.1f}% Complete"



#quest & riddle related actions

def update_riddle_hints() -> str:
    """
    Updates the word_length_hint and word_count fields for any Riddle
    where those are currently null, based on the answer.
    """
    db = db_session()
    try:
        # 1) Fetch riddles missing hints or word counts
        riddles = (
            db.query(Riddle)
              .filter(
                  or_(
                      Riddle.word_length_hint.is_(None),
                      Riddle.word_count.is_(None)
                  )
              )
              .all()
        )

        # 2) Generate and apply new hints
        for r in riddles:
            r.word_length_hint = generate_word_length_hint(r.answer)
            r.word_count        = generate_word_count(r.answer)

        # 3) Commit changes
        db.commit()
        return "✅ Riddle hints updated successfully!"
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# Example invocation:
# message = update_riddle_hints()
# print(message)


def generate_word_length_hint(answer):
    """Generates a hint based on the number of characters in each word of the answer."""
    words = answer.split()  # Split the answer into words
    hint = " ".join(str(len(word)) for word in words)  # Replace each word with its length
    return hint

def generate_word_count(answer):
    word_count = len(answer.split())
    return word_count


def save_correct_answer(squire_id: int, quest_id: int, riddle_id: int) -> None:
    """
    Records that the squire has correctly answered a riddle.
    If an entry already exists, it ensures answered_correctly is True.
    """
    db = db_session()
    try:
        # Upsert logic: try to fetch existing progress
        progress = (
            db.query(SquireRiddleProgress)
              .filter_by(
                  squire_id=squire_id,
                  quest_id=quest_id,
                  riddle_id=riddle_id
              )
              .one_or_none()
        )
        if progress:
            progress.answered_correctly = True
        else:
            progress = SquireRiddleProgress(
                squire_id=squire_id,
                quest_id=quest_id,
                riddle_id=riddle_id,
                answered_correctly=True
            )
            db.add(progress)
        db.commit()
    except:
        db.rollback()
        raise
    finally:
        db.close()

def check_quest_completion(squire_id: int, quest_id: int) -> bool:
    """
    Returns True if the squire has completed the quest by answering
    all required riddles: (# of HARD riddles + 6).
    """
    db = db_session()
    try:
        # Total 'Hard' riddles for this quest
        total_hard = (
            db.query(func.count(Riddle.id))
              .filter(
                  Riddle.quest_id == quest_id,
                  Riddle.difficulty == 'Hard'
              )
              .scalar() or 0
        )
        total_required = total_hard + 6

        # Count correctly answered riddles for this quest
        answered = (
            db.query(func.count(SquireRiddleProgress.id))
              .filter(
                  SquireRiddleProgress.squire_id == squire_id,
                  SquireRiddleProgress.quest_id == quest_id,
                  SquireRiddleProgress.answered_correctly == True
              )
              .scalar() or 0
        )
        logging.debug(f"{total_required} {answered}")
        return answered >= total_required
    finally:
        db.close()

# Example usage:
# save_correct_answer(2, 15, 42)
# completed = check_quest_completion(2, 15)
# print("Quest complete:", completed)

def complete_quest(squire_id: int, quest_id: int) -> tuple[bool, list[str]]:
    """
    Handles quest completion:
      - Checks if all riddles are solved.
      - Grants special item reward.
      - Clears travel history.
      - Marks quest as completed.
      - Unlocks the next quest (sets its status to 'active').
    Returns a tuple: (was_completed, messages).
    """
    db = db_session()
    messages: list[str] = []
    try:
        # 1) Check completion via ORM helper
        from shared import check_quest_completion
        if not check_quest_completion(squire_id, quest_id):
            return False, ["🔎 You still have more riddles to solve in this quest!"]

        messages.append("🎉 Congratulations! You have completed this quest!")

        # 2) Grant special reward from Quest table
        quest = db.query(Quest).get(quest_id)
        if quest and quest.reward:
            inv = Inventory(
                squire_id=squire_id,
                item_name=quest.reward,
                description=f"Special reward for completing quest {quest_id}.",
                item_type='special',
                effective_against=quest.effective_against
            )
            db.add(inv)
            messages.append(f"🏆 You have received a special item: {quest.reward}!")

        # 3) Clear travel history
        db.query(TravelHistory).filter(TravelHistory.squire_id == squire_id).delete()

        # 4) Upsert SquireQuestStatus to 'completed'
        status = (
            db.query(SquireQuestStatus)
              .filter_by(squire_id=squire_id, quest_id=quest_id).first()

        )
        if status:
            status.status = 'completed'
        else:
            status = SquireQuestStatus(
                squire_id=squire_id,
                quest_id=quest_id,
                status='completed'
            )
            db.add(status)

        # 5) Unlock next quest
        next_q = (
            db.query(Quest)
              .filter(Quest.id > quest_id)
              .order_by(Quest.id.asc())
              .first()
        )
        if next_q:
            next_q.status = 'active'
            messages.append(f"🛡️ A new quest has been unlocked: Quest {next_q.id}!")
        else:
            messages.append("⚠️ No more quests available!")

        # 6) Commit all changes
        db.commit()
        return True, messages

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# Example usage:
# completed, msgs = complete_quest(squire_id=2, quest_id=15)
# for line in msgs:
#     print(line)

def get_random_riddle(quest_id: int, squire_id: int):
    """
    Returns a single random unanswered Riddle for the given quest and squire,
    choosing difficulty based on how many they've already solved:
      <3 → Easy, <6 → Medium, else Hard.
    Returns a dict with riddle fields or None.
    """
    db = db_session()
    try:
        # 1) Count how many riddles they've answered correctly
        answered_count = (
            db.query(func.count(SquireRiddleProgress.id))
              .filter(
                  SquireRiddleProgress.squire_id == squire_id,
                  SquireRiddleProgress.quest_id == quest_id,
                  SquireRiddleProgress.answered_correctly == True
              )
              .scalar() or 0
        )

        # 2) Determine difficulty
        if answered_count < 3:
            difficulty = "Easy"
        elif answered_count < 6:
            difficulty = "Medium"
        else:
            difficulty = "Hard"

        # 3) Build a subquery of already answered riddle IDs
        answered_subq = (
            db.query(SquireRiddleProgress.riddle_id)
              .filter(SquireRiddleProgress.squire_id == squire_id)
        )

        # 4) Fetch one random unanswered riddle of that difficulty
        riddle = (
            db.query(
                Riddle.id,
                Riddle.riddle_text,
                Riddle.difficulty,
                Riddle.answer,
                Riddle.hint,
                Riddle.word_length_hint
            )
            .filter(
                Riddle.quest_id == quest_id,
                Riddle.difficulty == difficulty,
                ~Riddle.id.in_(answered_subq)
            )
            .order_by(func.rand())
            .first()
        )

        # 5) Return as dict or None
        return dict(riddle._asdict()) if riddle else None

    finally:
        db.close()

# Example:
# r = get_random_riddle(quest_id=17, squire_id=2)
# if r:
#     print("Random Riddle:", r)


def encounter_riddle(quest_id: int, squire_id: int) -> str:
    """
    Console-based riddle encounter:
      - Fetches a random unanswered riddle
      - Optionally shows a lexicon clue if the squire has a 'Lexicon' item
      - Prompts for an answer and handles correct/incorrect logic
    Returns a result message.
    """
    db = db_session()
    try:
        # 1) Get a random riddle via ORM helper
        riddle = get_random_riddle(quest_id, squire_id)
        if not riddle:
            return "🏆 You've mastered all riddles for this quest! No more questions remain."

        # 2) Display the riddle
        print(f"\n📜 Riddle ({riddle['difficulty']}): {riddle['riddle_text']}")

        # 3) Check for 'Lexicon' in inventory to show word-length hint
        magic_count = (
            db.query(func.count(Inventory.id))
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_name.ilike("%Lexicon%")
              )
              .scalar() or 0
        )
        if magic_count > 0:
            print(f"💡 Clue: {riddle['word_length_hint']} (Number of letters in each word)")

        # 4) Prompt for answer
        answer = input("Enter your answer: ").strip().lower()

        # 5) Validate
        if answer == riddle["answer"].strip().lower():
            # Correct!
            # Determine rewards by difficulty
            xp_reward = 10 if riddle["difficulty"] == "Easy" else 20 if riddle["difficulty"] == "Medium" else 30
            gold_reward = 5 if riddle["difficulty"] == "Easy" else 15 if riddle["difficulty"] == "Medium" else 50

            # Apply progress and capture any level-up messages
            levelup_msgs = update_squire_progress(squire_id, xp_reward, gold_reward)

            # Record that the riddle was answered correctly
            save_correct_answer(squire_id, quest_id, riddle["id"])

            # Build result string
            msg = f"✅ Correct! You gain {xp_reward} XP and {gold_reward} bits!"
            if levelup_msgs:
                msg += " " + " ".join(levelup_msgs)
            return msg

        else:
            # Incorrect: show hint
            return f"❌ Incorrect! Hint: {riddle['hint']}"

    finally:
        db.close()

# Example usage:
# result = encounter_riddle(quest_id=17, squire_id=2)
# print(result)

def check_riddle_answer(user_answer: str, riddle_id: int) -> bool:
    """
    Returns True if the provided user_answer matches the stored answer for the given riddle_id.
    """
    db = db_session()
    try:
        riddle = db.query(Riddle).get(riddle_id)
        if not riddle or not riddle.answer:
            return False
        return user_answer.lower().strip() == riddle.answer.lower().strip()
    finally:
        db.close()

def get_active_quests(squire_id: int) -> list[dict]:
    """
    Returns a list of one available quest (id, quest_name, description) for the squire
    that has not yet been completed.
    """
    db = db_session()
    try:
        # Subquery to find completed quest IDs
        completed_ids = (
            db.query(SquireQuestStatus.quest_id)
              .filter(
                  SquireQuestStatus.squire_id == squire_id,
                  SquireQuestStatus.status == 'completed'
              )
        )
        # Fetch the first active quest not in completed_ids
        quest = (
            db.query(Quest.id, Quest.quest_name, Quest.description)
              .filter(~Quest.id.in_(completed_ids))
              .order_by(Quest.id.asc())
              .first()
        )
        if quest:
            return [dict(quest._asdict())]
        return []
    finally:
        db.close()

# Example usage:
# result = check_riddle_answer("offer", 42)
# active = get_active_quests(squire_id=2)
# print("Answer correct:", result)
# print("Available quests:", active)


# Display available quests
def chooseq(conn, squire_id):
    quests = get_active_quests(conn, squire_id)

    print("\n🏰 Available Quests:")
    for q in quests:
        print(f"[{q['id']}] {q['quest_name']}: {q['description']}")

    quest_id = int(input("\nEnter the Quest ID to embark on your journey: "))
    return quest_id

def get_riddles_for_quest(quest_id: int) -> list[dict]:
    """
    Returns all riddles for a given quest as a list of dicts containing:
    id, riddle_text, answer, hint.
    """
    db = db_session()
    try:
        riddles = (
            db.query(Riddle)
              .filter(Riddle.quest_id == quest_id)
              .all()
        )
        return [
            {
                'id': r.id,
                'riddle_text': r.riddle_text,
                'answer': r.answer,
                'hint': r.hint
            }
            for r in riddles
        ]
    finally:
        db.close()


def visit_shop(squire_id: int, level: int) -> None:
    """
    Console-based shop interaction using ORM:
      - Lists available ShopItem entries up to the player's level.
      - Shows current gold from the squire's Team.
      - Prompts purchase choice; updates Team.gold and Inventory.
    """
    db = db_session()
    try:
        # 1) Fetch shop items available at this level
        items = (
            db.query(ShopItem)
              .filter(ShopItem.min_level <= level)
              .all()
        )
        print("\n🛒 Welcome to the Bit Mall! Here's what we have:")
        for item in items:
            print(f"  [{item.id}] {item.item_name} - {item.description} "
                  f"(💰 {item.price} bits, 🍴 {item.uses} uses)")

        # 2) Get squire's team and current gold
        squire = db.query(Squire).get(squire_id)
        team = db.query(Team).get(squire.team_id) if squire else None
        player_gold = team.gold if team and team.gold is not None else 0
        print(f"\n💰 You have {player_gold} Bitcoin.")

        choice = input("Enter the item ID to buy or 'Q' to exit: ").strip().upper()
        if choice == "Q":
            print("🏪 You leave the shop.")
            return

        # 3) Attempt purchase
        try:
            item_id = int(choice)
        except ValueError:
            print("❌ Invalid input. Please enter a number or 'Q'.")
            return

        shop_item = db.query(ShopItem).get(item_id)
        if not shop_item:
            print("❌ Invalid selection.")
            return
        if player_gold < shop_item.price:
            print("❌ You don't have enough gold!")
            return

        # 4) Deduct gold and add to inventory
        team.gold = player_gold - shop_item.price
        new_inv = Inventory(
            squire_id=squire_id,
            item_name=shop_item.item_name,
            description=shop_item.description,
            item_type=shop_item.item_type,
            uses_remaining=shop_item.uses
        )
        db.add(new_inv)
        db.commit()

        print(f"✅ You bought {shop_item.item_name}!")
    finally:
        db.close()

# Example usage:
# print(get_riddles_for_quest(quest_id=15))
# visit_shop(squire_id=2, level=1)

def consume_food(squire_id: int) -> tuple[bool, str]:
    """
    Uses up food from the squire's inventory when traveling.
    - Applies a level-based chance to avoid consumption.
    - Deducts one use from the first available food item or removes it.
    Returns (success, message).
    """
    db = db_session()
    try:
        # 1) Fetch squire level
        squire = db.query(Squire).get(squire_id)
        level = squire.level if squire else 1

        # 2) Define reduction chances
        hunger_reduction = {1: 0, 2: 10, 3: 25, 4: 50, 5: 75}
        avoid_chance = hunger_reduction.get(level, 0)

        # 3) Random roll to skip consumption
        if random.randint(1, 100) <= avoid_chance:
            return True, "🌟 Your experience helps you travel efficiently! You avoid hunger this time."

        # 4) Find an available food item
        food_item = (
            db.query(Inventory)
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_type == 'food',
                  Inventory.uses_remaining > 0
              )
              .first()
        )

        if not food_item:
            return False, "🚫 No food available! You feel the pangs of hunger."

        # 5) Consume one use
        food_item.uses_remaining -= 1
        item_name = food_item.item_name

        if food_item.uses_remaining <= 0:
            db.delete(food_item)
            message = f"🗑️ You finished your {item_name}."
        else:
            message = f"🍽️ You used your {item_name}. Remaining uses: {food_item.uses_remaining}."

        db.commit()
        return True, message

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# Example usage:
# success, msg = consume_food(squire_id=2)
# print(msg)
