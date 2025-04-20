import random
import pymysql
import logging
from db import Squire, Course, Team, engine, db_session, Team, TravelHistory, Quest, SquireQuestion, SquireRiddleProgress, Riddle, Enemy, Inventory, WizardItem, Job, MapFeature, MultipleChoiceQuestion, TrueFalseQuestion, ShopItem, SquireQuestStatus, TeamMessage, TreasureChest, XpThreshold
from sqlalchemy import not_, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def generate_random_coordinates(difficulty):
    """Assigns a treasure chest location based on riddle difficulty."""
    if difficulty == "Easy":
        return random.randint(-10, 10), random.randint(-10, 10)
    elif difficulty == "Medium":
        return random.randint(-20, 20), random.randint(-20, 20)
    else:  # Hard
        return random.randint(-35, 35), random.randint(-35, 35)

def generate_rewards(difficulty):
    """Assigns rewards based on riddle difficulty."""
    if difficulty == "Easy":
        return random.randint(10, 20), random.randint(5, 15), random.randint(1, 2), None
    elif difficulty == "Medium":
        return random.randint(25, 40), random.randint(15, 25), random.randint(2, 3), random.choice(["Small Shield", None])
    else:  # Hard
        return random.randint(50, 75), random.randint(30, 50), random.randint(3, 5), random.choice(["Ring of Protection", "Golden Amulet", None])


def insert_treasure_chests(quest_id: int, squire_quest_id: int) -> str:
    """
    Inserts a TreasureChest record for each Riddle in the given quest
    that doesn’t already have a chest for this squire_quest_id.
    Returns a status message.
    """
    db = db_session()
    message = "No new treasure chests created for this quest, Squire."
    try:
        # 1) Find riddle IDs already used for this squire’s quest
        existing = (
            db.query(TreasureChest.riddle_id)
              .filter(TreasureChest.squire_quest_id == squire_quest_id)
              .subquery()
        )
        # 2) Query all other riddles for this quest
        riddles = (
            db.query(Riddle.id, Riddle.difficulty)
              .filter(
                  Riddle.quest_id == quest_id,
                  not_(Riddle.id.in_(select(existing)))
              )
              .all()
        )

        # 3) Insert chests for each missing riddle
        for riddle_id, difficulty in riddles:
            x, y = generate_random_coordinates(difficulty)
            gold, xp, food, special_item = generate_rewards(difficulty)

            chest = TreasureChest(
                x_coordinate     = x,
                y_coordinate     = y,
                riddle_id        = riddle_id,
                gold_reward      = gold,
                xp_reward        = xp,
                food_reward      = food,
                special_item     = special_item,
                squire_quest_id  = squire_quest_id
            )
            db.add(chest)

        if riddles:
            db.commit()
            message = "✅ Treasure chests inserted successfully!"
        return message

    except Exception as e:
        db.rollback()
        logging.warning(f"Error inserting treasure chests for quest {quest_id}, squire_quest {squire_quest_id}: {e}")
        return f"⚠️ Failed to insert new treasure chests: {e}"
    finally:
        db.close()

# Example:
# msg = insert_treasure_chests_orm(quest_id=15, squire_quest_id=42)
# print(msg)

def generate_terrain_features_dynamic(
    session: Session,
    squire_id: int,
    squire_quest_id: int,
    num_forest_clusters: int = 5,
    cluster_size: int = 10,
    max_forests: int = 75,
    num_mountain_ranges: int = 3,
    mountain_range_length: int = 9,
    max_mountains: int = 45,
):
    """
    ORM-based rewrite of dynamic terrain generation:
    - Rivers, forest clusters, and mountain ranges are placed around the map center.
    - Avoids overlapping existing map features and unopened treasure chests.
    """
    # 1. Fetch squire level
    level = session.query(Squire.level).filter(Squire.id == squire_id).scalar()
    placement_radius = 10 + level * 2

    # 2. Build restricted set of coordinates
    restricted = set(
        session.query(MapFeature.x_coordinate, MapFeature.y_coordinate)
        .filter(MapFeature.squire_id == squire_id)
        .all()
    )
    treasure_coords = session.query(TreasureChest.x_coordinate, TreasureChest.y_coordinate)\
        .filter(
            TreasureChest.squire_quest_id == squire_quest_id,
            TreasureChest.is_opened == False
        ).all()
    restricted.update(treasure_coords)
    restricted.update({(0, 0), (40, 40)})

    to_add = []  # collect new MapFeature instances

    # 3. River
    river_exists = session.query(MapFeature).filter_by(squire_id=squire_id, terrain_type='river').count()
    if river_exists == 0:
        x = -placement_radius
        y = random.randint(-placement_radius, placement_radius)
        for _ in range(25 + level * 2):
            if (x, y) not in restricted:
                to_add.append(MapFeature(
                    x_coordinate=x,
                    y_coordinate=y,
                    squire_id=squire_id,
                    terrain_type='river'
                ))
                restricted.add((x, y))
            x += 1
            y += random.choice([-1, 0, 1])

    # 4. Forest clusters
    existing_forests = session.query(MapFeature).filter_by(squire_id=squire_id, terrain_type='forest').count()
    forests_needed = max_forests - existing_forests
    clusters = min(num_forest_clusters, forests_needed // cluster_size)
    for _ in range(clusters):
        cx = random.randint(-placement_radius, placement_radius)
        cy = random.randint(-placement_radius, placement_radius)
        for _ in range(cluster_size):
            fx = cx + random.randint(-2, 2)
            fy = cy + random.randint(-2, 2)
            if len([f for f in to_add if f.terrain_type=='forest']) >= forests_needed:
                break
            if (fx, fy) not in restricted:
                to_add.append(MapFeature(
                    x_coordinate=fx,
                    y_coordinate=fy,
                    squire_id=squire_id,
                    terrain_type='forest'
                ))
                restricted.add((fx, fy))

    # 5. Mountain ranges
    existing_mountains = session.query(MapFeature).filter_by(squire_id=squire_id, terrain_type='mountain').count()
    mountains_needed = max_mountains - existing_mountains
    ranges = min(num_mountain_ranges, mountains_needed // mountain_range_length)
    for _ in range(ranges):
        mx = random.randint(-placement_radius, placement_radius)
        my = random.randint(-placement_radius, placement_radius)
        horizontal = random.choice([True, False])
        for i in range(mountain_range_length):
            x = mx + (i if horizontal else 0)
            y = my + (0 if horizontal else i)
            if len([m for m in to_add if m.terrain_type=='mountain']) >= mountains_needed:
                break
            if (x, y) not in restricted:
                to_add.append(MapFeature(
                    x_coordinate=x,
                    y_coordinate=y,
                    squire_id=squire_id,
                    terrain_type='mountain'
                ))
                restricted.add((x, y))

    # 6. Persist all new features in one batch
    session.add_all(to_add)
    session.commit()


def generate_river_path(start_x, start_y, length, bendiness=0.6, restricted=set()):
    river = []
    x, y = start_x, start_y
    river.append((x, y))

    for _ in range(length):
        dx = random.choice([1, 0, -1]) if random.random() < bendiness else 1
        dy = random.choice([1, 0, -1]) if random.random() < bendiness else 0

        x += dx
        y += dy

        # Prevent overlap with other features
        while (x, y) in restricted:
            dx = random.choice([-1, 0, 1])
            dy = random.choice([-1, 0, 1])
            x += dx
            y += dy

        river.append((x, y))
        restricted.add((x, y))  # Mark river location as restricted too

    return river
