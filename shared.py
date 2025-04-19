import random
import logging
import pymysql
import os
import decimal
import configparser
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ************************************
# This Python Script created 3/4/25 TF
# This script contains consolidated functions for use by the game play
# ************************************


# travel
def log_travel_history(squire_id, x, y, conn):
    """Logs the player's movement in the travel_history table."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Insert position if not already logged
    cursor.execute("""
        INSERT IGNORE INTO travel_history (squire_id, x_coordinate, y_coordinate)
        VALUES (%s, %s, %s)
    """, (squire_id, x, y))

    conn.commit()
    cursor.close()

def can_enter_tile(squire_id, new_x, new_y, conn):
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    # Assume you have a table or function to determine the tile type at these coordinates
    cursor.execute("SELECT terrain_type FROM map_features WHERE x_coordinate = %s AND y_coordinate = %s and squire_id=%s", (new_x, new_y, squire_id))
    tile = cursor.fetchone()

    # If the destination is a mountain, check for boots
    if tile and tile["terrain_type"] == "mountain":
        cursor.execute("SELECT * FROM inventory WHERE squire_id = %s AND item_name like '%%Boots%%'", (squire_id,))
        boots = cursor.fetchone()
        cursor.close()
        return bool(boots)  # Only allow entry if boots exist

    if tile and tile["terrain_type"] == "river":
        cursor.execute("SELECT * FROM inventory WHERE squire_id = %s AND item_name like '%%Boat%%'", (squire_id,))
        boat = cursor.fetchone()
        cursor.close()
        return bool(boat)  # Only allow entry if boots exist


    cursor.close()
    return True

def update_player_position(squire_id, direction, conn):
    """Updates the player's coordinates based on movement direction."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch current coordinates
    cursor.execute("SELECT x_coordinate, y_coordinate FROM squires WHERE id = %s", (squire_id,))
    position = cursor.fetchone()

    if not position:
        logging.error("❌ ERROR: Player position not found in update_player_position!")
        return

    x_orig, y_orig = position["x_coordinate"], position["y_coordinate"]

    # Update coordinates based on direction
    if direction == "N":
        x = x_orig
        y = y_orig + 1
    elif direction == "S":
        x = x_orig
        y = y_orig - 1
    elif direction == "E":
        x = x_orig + 1
        y = y_orig
    elif direction == "W":
        x = x_orig - 1
        y = y_orig
    elif direction == "V":
        x = 0
        y = 0
    else:
        # Default to current position if direction is not recognized
        x = x_orig
        y = y_orig

    logging.debug(f"{direction}, {x_orig}, {y_orig}, {x}, {y}")

    # Save new position
    if can_enter_tile(squire_id, x, y, conn):
        cursor.execute("UPDATE squires SET x_coordinate = %s, y_coordinate = %s WHERE id = %s", (x, y, squire_id))
        conn.commit()
        cursor.close()
        log_travel_history(squire_id, x, y, conn)
        message = f"🌿 You travel unhindered towards the {direction}."
        return x, y, message
    else:
        cursor.execute("UPDATE squires SET x_coordinate = %s, y_coordinate = %s WHERE id = %s", (x_orig, y_orig, squire_id))
        conn.commit()
        cursor.close()
        message = "❌ Sorry, but you have to take the long way around that map feature."
        return x_orig, y_orig, message

#experimental for narrowing tiles that can be viewed
def get_viewport_map(squire_id, quest_id, conn, viewport_size=15):
    """Generates an HTML-based map showing only a viewport (e.g., 15x15) around the player."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch visited locations
    cursor.execute("SELECT x_coordinate, y_coordinate FROM travel_history WHERE squire_id = %s", (squire_id,))
    visited_locations = { (row["x_coordinate"], row["y_coordinate"]) for row in cursor.fetchall() }

    # Fetch player's position
    cursor.execute("SELECT x_coordinate, y_coordinate FROM squires WHERE id = %s", (squire_id,))
    position = cursor.fetchone()
    if not position:
        return "<p>⚠️ Error: Player position not found.</p>"
    x, y = position["x_coordinate"], position["y_coordinate"]

    # Fetch feature locations (e.g., forests, mountains, etc.)
    cursor.execute("SELECT x_coordinate, y_coordinate, terrain_type FROM map_features where squire_id = %s",(squire_id,))
    features = cursor.fetchall()
    feature_map = { (row["x_coordinate"], row["y_coordinate"]): row["terrain_type"] for row in features }

    cursor.close()

    # Define viewport boundaries (centered on the player)
    half = viewport_size // 2
    x_min = x - half
    x_max = x + half
    y_min = y - half
    y_max = y + half

    # Start building the HTML table for the viewport map
    map_html = '<table class="game-map" style="border-collapse: collapse;">'
    for row in reversed(range(y_min, y_max + 1)):  # Reverse rows for correct display
        map_html += "<tr>"
        for col in range(x_min, x_max + 1):
            cell_content = "⬜"  # Default: unexplored tile
            if (col, row) == (x, y):
                cell_content = "📍"  # Player position
            elif (col, row) == (0, 0):
                cell_content = "🏰"  # Home village
            elif (col, row) == (40,40):
                cell_content = "🏰"  # Enemy village
            elif (col, row) in feature_map:
                terrain = feature_map[(col, row)]
                if terrain == "forest":
                    cell_content = "🌲"
                elif terrain == "mountain":
                    cell_content = "🏔️"
                elif terrain == "river":
                    cell_content = "🌊"
            elif (col, row) in visited_locations:
                cell_content = "•"  # Visited location

            map_html += f'<td style="width: 30px; height: 30px; text-align: center; border: 1px solid black;">{cell_content}</td>'
        map_html += "</tr>"
    map_html += "</table>"

    # Add a legend below the map
    map_html += """
    <br>
    <p>📍 = Your Position | • = Visited | 🏰 = Home Village | 🌲 = Forest | 🏔️ = Mountain | ⬜ = Unexplored</p>
    """
    return map_html

def display_travel_map(squire_id, quest_id, conn):
    """Generates an HTML-based map showing forests, visited locations, and the player."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch visited locations
    cursor.execute("SELECT x_coordinate, y_coordinate FROM travel_history WHERE squire_id = %s", (squire_id,))
    visited_locations = { (row["x_coordinate"], row["y_coordinate"]) for row in cursor.fetchall() }

    # Fetch player's position
    cursor.execute("SELECT x_coordinate, y_coordinate FROM squires WHERE id = %s", (squire_id,))
    position = cursor.fetchone()
    x, y = position["x_coordinate"], position["y_coordinate"]

    # Fetch feature locations
    cursor.execute("SELECT x_coordinate, y_coordinate, terrain_type FROM map_features where squire_id=%s",(squire_id,))
    features = cursor.fetchall()

    #logging.debug(f"DEBUG of features: {features}")
    feature_map = { (row["x_coordinate"], row["y_coordinate"]): row["terrain_type"] for row in features }


    #logging.debug(f"🚀 DEBUG: Features fetched from DB → {feature_map}")  # ✅ Print features before map processing

    cursor.close()

    # Determine grid boundaries dynamically
    all_points = visited_locations | set(feature_map.keys()) | {(x, y), (0, 0)}


    # Ensure there are valid points
    if all_points:
        min_x, max_x = min(vx for vx, vy in all_points), max(vx for vx, vy in all_points)
        min_y, max_y = min(vy for vx, vy in all_points), max(vy for vx, vy in all_points)
    else:
        min_x, max_x, min_y, max_y = -4, 4, -4, 4  # Default grid size

    grid_width = max_x - min_x + 1
    grid_height = max_y - min_y + 1

    # Ensure grid dimensions are valid
    if grid_width <= 0 or grid_height <= 0:
        return "<p>⚠️ Error: Invalid grid dimensions.</p>"

    # Start building the HTML table for the map
    map_html = '<table class="game-map" style="border-collapse: collapse;">'

    for row in reversed(range(min_y, max_y + 1)):  # Flip Y-axis for correct display
        map_html += "<tr>"

        for col in range(min_x, max_x + 1):
            cell_content = "⬜"  # Default empty tile

            if (col, row) == (x, y):
                cell_content = "📍"  # Player position
            elif (col, row) == (0, 0):
                cell_content = "🏰"  # Home village
            elif (col, row) in feature_map:
                terrain = feature_map[(col,row)]

                if terrain == "forest":
                    cell_content = "🌲"  # Forest
                elif terrain == "mountain":
                    cell_content = "🏔️"
            elif (col, row) in visited_locations:
                cell_content = "•"  # Visited location

            map_html += f'<td style="width: 30px; height: 30px; text-align: center; border: 1px solid black;">{cell_content}</td>'

        map_html += "</tr>"

    map_html += "</table>"

    # Add a legend below the map
    map_html += """
    <br>
    <p>📍 = Your Position | • = Visited | 🏰 = Home Village | 🌲 = Forest | 🏔️ = Mountain | ⬜ = Unexplored</p>
    """

    #logging.debug(f"🚀 DEBUG: Generated game map:\n{map_html}")
    return map_html

# TREASURE! AAAARRRRRRRRRRRRR.

def ishint(squire_id, conn):
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT count(*) as inv from inventory where squire_id = %s and item_name like %s",(squire_id,'%%lexiconis%%'))
    hint = cursor.fetchone()["inv"]

    if hint > 0:
        return True
    else:
        return False

def iswordlengthhint(squire_id, conn):
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT count(*) as inv from inventory where squire_id = %s and item_name like %s",(squire_id,'%%lexiconis%%'))
    hint = cursor.fetchone()["inv"]

    if hint > 0:
        return True
    else:
        return False

def iswordcounthint(squire_id, conn):
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT count(*) as inv from inventory where squire_id = %s and item_name like %s",(squire_id,'%%four-leaf clover%%'))
    hint = cursor.fetchone()["inv"]

    if hint > 0:
        return True
    else:
        return False

def check_for_treasure_at_location(squire_id, x, y, conn, q, sqid):
    """Checks if there's a treasure chest exactly at the player's current position."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    cursor.execute(f"""
    SELECT tc.*
        FROM treasure_chests tc
        JOIN riddles r ON tc.riddle_id = r.id
        LEFT JOIN squire_riddle_progress srp ON r.id = srp.riddle_id AND srp.squire_id = %s
        WHERE r.quest_id = %s
        AND tc.x_coordinate = %s
        AND tc.y_coordinate = %s
        AND tc.squire_quest_id = %s
        AND srp.riddle_id IS NULL;

    """,(squire_id,q,x,y,sqid))

    return cursor.fetchone()  # **Only return chest if it's at (x, y)**


def check_for_treasure(squire_id, conn, q):
    """Checks if a treasure chest exists at the player's current location."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Get player's current coordinates
    cursor.execute("SELECT x_coordinate, y_coordinate FROM squires WHERE id = %s", (squire_id,))
    position = cursor.fetchone()
    x, y = position["x_coordinate"], position["y_coordinate"]

    # Check if there's a chest at this location
    cursor.execute(f"""
    SELECT tc.*
        FROM treasure_chests tc
        JOIN riddles r ON tc.riddle_id = r.id
        LEFT JOIN squire_riddle_progress srp ON r.id = srp.riddle_id AND srp.squire_id = %s
        WHERE r.quest_id = %s
        AND tc.x_coordinate = %s
        AND tc.y_coordinate = %s
        AND srp.riddle_id IS NULL;

    """,(squire_id,q,x,y,))
    #SELECT * FROM treasure_chests WHERE riddle_id in (select id from riddles where quest_id = {q}) and x_coordinate = %s AND y_coordinate = %s AND is_opened = FALSE", (x, y))
    chest = cursor.fetchone()

    if not chest:
        return None  # No chest here

    return chest  # Return chest details

def open_treasure_chest(squire_id, chest, conn):
    """Handles treasure chest interaction and riddle solving."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    val = None

    print("\n🎁 You have discovered a Treasure Chest!")
    print("🔒 The chest is locked... Solve the riddle to open it!")

    # Fetch the riddle
    cursor.execute("SELECT riddle_text, answer, word_length_hint, quest_id, difficulty FROM riddles WHERE id = %s", (chest["riddle_id"],))
    riddle = cursor.fetchone()

    print(f"\n📜 Riddle: {riddle['riddle_text']}")
    c = conn.cursor()
    c.execute("SELECT count(*) as magic from INVENTORY where squire_id = %s and item_name like %s ",(squire_id, "%Lexicon%"))
    result = c.fetchone()
    magic = result["magic"] if result else 0  # Default to 0 if result is None
    logging.debug(f"Test for Lexicon in Inventory: {magic}")

    if magic > 0:
        print(f"💡 Clue: {riddle['word_length_hint']} (Number of letters in each word)")
    c.close()

    answer = input("Enter your answer: ").strip().lower()

    if answer == riddle["answer"].strip().lower():

        val = "✅ Correct! The chest unlocks, revealing its treasures!"
        print()

        # Reward the player
        gold = chest["gold_reward"]
        xp = chest["xp_reward"]
        food = chest["food_reward"]
        special_item = chest["special_item"]

        if gold > 0:
            val += f"💰 You found {gold} bitcoin!"
            cursor.execute("UPDATE teams SET gold = gold + %s WHERE id = (SELECT team_id FROM squires WHERE id = %s)", (gold, squire_id))

        if xp > 0:
            val += f"🎖️ You gained {xp} XP!"
            cursor.execute("UPDATE squires SET experience_points = experience_points + %s WHERE id = %s", (xp, squire_id))

        if food > 0:
            val += f"🍖 You found {food} special food items!"
            cursor.execute("INSERT INTO inventory (squire_id, item_name, description, uses_remaining, item_type) VALUES (%s, 'Magic Pizza', 'Restores hunger', 15, 'food')", (squire_id,))

        if special_item:

            if riddle['difficulty'] == 'Easy':
                uses_remain = 10
            elif riddle['difficulty'] == 'Medium':
                uses_remain = 25
            else:
                uses_remain = 50

            val += f"🛡️ You discovered a rare item: {special_item}!"
            cursor.execute("INSERT INTO inventory (squire_id, item_name, description, uses_remaining, item_type) VALUES (%s, %s, 'A special item that affects gameplay', %s, 'gear')", (squire_id, special_item, uses_remain))

        # Mark the chest as opened
        cursor.execute("UPDATE treasure_chests SET is_opened = TRUE WHERE id = %s", (chest["id"],))
        cursor.execute("INSERT INTO squire_riddle_progress (squire_id, riddle_id, quest_id, answered_correctly) VALUES (%s, %s, %s, 1)", (squire_id,chest["riddle_id"],riddle["quest_id"],))
        conn.commit()

    else:
        val = "❌ Incorrect! The chest remains locked. Try again later."

    cursor.close()
    return val

def calculate_riddle_reward(conn, r, s):
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT level from squires where id = %s", (s,))
    level = cursor.fetchone()["level"]

    logging.debug(f"Calc Riddle Reward: {level}")

    if level:
        cursor.execute("SELECT item_name, uses, min_level FROM wizard_items where min_level <= %s ORDER BY RAND() LIMIT 1",(level,))
        item = cursor.fetchone()

        logging.debug(f"Calc Riddle Reward: {item}")

        if item:
            special_item = item["item_name"]
            u = item["uses"]

            logging.debug(f"Calc Riddle Reward: {special_item}, {u}")

            cursor.execute("SELECT difficulty from riddles where id = %s", (r,))
            difficulty = cursor.fetchone()["difficulty"]

            logging.debug(f"Calc Riddle Reward: {difficulty}")

            if difficulty == 'Easy':
                u = u
            elif difficulty == "Medium":
                u += 10
            else:
                u += 25

            query = "INSERT INTO inventory (squire_id, item_name, description, uses_remaining, item_type) VALUES (%s,%s,%s,%s,%s)"
            values = (s, special_item, "magical item affecting game play", u, "gear")
            logging.debug(query)
            logging.debug(values)

            if cursor.execute(query, values):
                conn.commit()
                cursor.close()
                return special_item
            else:
                cursor.close()
                return "nothing because knowledge is its own reward."


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


def calculate_enemy_encounter_probability(squire_id, quest_id, current_x, current_y, conn, squire_quest_id, proximity=2):
    """
    Calculates the probability of encountering an enemy based on nearby features.

    Args:
        squire_id (int): The player's ID.
        quest_id (int): The current quest ID.
        current_x (int): Player's current x coordinate.
        current_y (int): Player's current y coordinate.
        conn: Database connection.
        proximity (int): Distance within which features affect enemy chance.

    Returns:
        float: A probability between 0 and 1.
    """
    base_probability = 0.05

    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Adjust probability based on nearby map features (e.g., forests, mountains)
    cursor.execute("""
        SELECT terrain_type, COUNT(*) as count
        FROM map_features
        WHERE ABS(x_coordinate - %s) <= %s AND ABS(y_coordinate - %s) <= %s
        GROUP BY terrain_type
    """, (current_x, proximity, current_y, proximity))
    features = cursor.fetchall()

    # Increase probability per feature type
    for feature in features:
        if feature["terrain_type"] == "forest":
            base_probability += 0.02 * feature["count"]
        elif feature["terrain_type"] == "mountain":
            base_probability += 0.03 * feature["count"]
        elif feature["terrain_type"] == "river":
            base_probability += 0.04 * feature["count"]

    # Check for nearby unopened treasure chests
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM treasure_chests
        WHERE ABS(x_coordinate - %s) <= %s AND ABS(y_coordinate - %s) <= %s AND squire_quest_id = %s AND is_opened = 0
    """, (current_x, proximity, current_y, proximity, squire_quest_id))
    chest_result = cursor.fetchone()
    if chest_result and chest_result["count"] > 0:
        # Treasure chests might lure enemies—or maybe they're cursed!
        base_probability += 0.04 * chest_result["count"]

    # Clamp the probability between 0 and 1
    probability = min(max(base_probability, 0.0), 0.9)
    cursor.close()
    return probability

def calculate_hit_chance(squire_id, level, conn):
    """Calculates hit chance based on the number of correctly answered questions."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT count(*) as all_TF from true_false_questions;")
    total_tf_qs = cursor.fetchone()["all_TF"]

    cursor.execute("SELECT count(*) as all_riddles from riddles;")
    total_riddles = cursor.fetchone()["all_riddles"]

    allqs = total_tf_qs + total_riddles

    # ✅ Count the number of unique correctly answered questions
    cursor.execute("""
        SELECT COUNT(DISTINCT question_id) AS correct_answers
        FROM squire_questions
        WHERE squire_id = %s AND answered_correctly = TRUE
    """, (squire_id,))
    result = cursor.fetchone()
    correct_answers = result["correct_answers"] if result else 0

    combatmod = correct_answers / allqs

    # ✅ Calculate hit chance (50% + 0.5% per correct answer)
    base_hit_chance = (level * 2) + (combatmod)

    # ✅ Cap hit chance at 95%
    return min(base_hit_chance, 95)

def combat_mods(squid,enemy,level,conn):
    #gear items in inventory each increase combat odds by 1 for the player
    #special items increase combat odds against particular enemies
    #hit chances are also modified by the player level
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT count(*) as gear_items from inventory where squire_id = %s and item_type = 'gear' and uses_remaining > 0", (squid,))
    base_mod = cursor.fetchone()['gear_items']

    cursor.execute("SELECT count(*) as count_special_items from inventory  where item_type = 'special' and squire_id = %s and effective_against = %s", (squid,enemy,))
    enemy_mod = cursor.fetchone()['count_special_items']

    level_mod = 2 * level

    total_mods = base_mod + (enemy_mod * 5) + level_mod

    logging.debug(f"Squire: {squid}, Enemy: {enemy}, All Mods: {total_mods}")
    cursor.close()
    return total_mods

def hunger_mods(squid,conn):
    #certain special items will modify the player's hunger level
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("""
    SELECT count(*) as spec_food from inventory where item_name = 'gold coin pouch' and squire_id = %s
    """,(squid,))
    food_mod = cursor.fetchone()["spec_food"]

    cursor.close()

    return food_mod

def degrade_gear(squire_id, weapon, conn):
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    #this section degrades the weapon used in combat
    cursor.execute ("SELECT id, uses_remaining from inventory WHERE squire_id = %s and CAST(item_name AS CHAR) = %s ORDER BY uses_remaining LIMIT 1", (squire_id,weapon,))
    inv = cursor.fetchone()

    if inv:
        uses = inv["uses_remaining"] - 1
        cursor.execute ("UPDATE inventory set uses_remaining = %s WHERE id = %s",(uses,inv["id"],))
        conn.commit()

        cursor.execute("DELETE from inventory where uses_remaining < 1 and squire_id = %s and CAST(item_name AS CHAR) = %s", (squire_id,weapon,))
        conn.commit()

    #this section degrades regular equipment in inventory after each combat action
    cursor.execute ("SELECT id, uses_remaining from inventory WHERE squire_id = %s and item_type = 'gear' and item_name not in ('Pen', 'Calculator', 'Law Book', 'Stamp')",(squire_id,))
    gear = cursor.fetchall()

    for  g in gear:
        left = g["uses_remaining"] - 1
        cursor.execute ("UPDATE inventory set uses_remaining = %s where id = %s", (left,g["id"]))
        conn.commit()

        cursor.execute("DELETE from inventory where uses_remaining < 1 and squire_id = %s and id = %s", (squire_id,g["id"],))
        conn.commit()

    cursor.close()
    return True

def update_work_for_combat(squire_id, conn):

    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Reset work session count if needed
    cursor.execute("UPDATE squires SET work_sessions = 0 WHERE id = %s", (squire_id,))
    if conn.commit():
        cursor.close()
        return False
    else:
        cursor.close()
        return False

def get_player_max_hunger(squire_id, conn):
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT sum(uses_remaining) as hunger FROM inventory WHERE item_type='food' and squire_id = %s", (squire_id,))
    max_hunger = cursor.fetchone()["hunger"] or 0

    cursor.execute("SELECT id, item_name, uses_remaining FROM inventory WHERE squire_id = %s AND item_type = 'food' AND uses_remaining > 0 LIMIT 1", (squire_id,))
    food = cursor.fetchone()

    return max_hunger, food

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

# stats & player functions
def get_squire_stats(squire_id, conn):
    """Fetch the player's current XP and gold."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("""
        SELECT s.experience_points, t.gold
        FROM squires s
        JOIN teams t ON s.team_id = t.id
        WHERE s.id = %s
    """, (squire_id,))

    stats = cursor.fetchone()
    cursor.close()

    if stats:
        return stats["experience_points"], stats["gold"]
    return 0, 0

def update_squire_progress(squire_id, conn, xp, gold):
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Update XP and check for level-up
    cursor.execute("UPDATE squires SET experience_points = experience_points + %s WHERE id = %s", (xp, squire_id))
    cursor.execute("UPDATE teams SET gold = gold + %s WHERE id = (SELECT team_id FROM squires WHERE id = %s)", (gold, squire_id))

    conn.commit()
    cursor.close()

    check_for_level_up(squire_id, conn)

def check_for_level_up(squire_id, conn):
    """Checks if a player has enough XP to level up and applies level-up bonuses."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Get current XP and level
    cursor.execute("SELECT experience_points, level FROM squires WHERE id = %s", (squire_id,))
    squire = cursor.fetchone()

    xp = squire["experience_points"]
    current_level = squire["level"]

    # XP thresholds for level-ups
    cursor.execute("SELECT level, min from xp_thresholds order by level;")
    level_data = cursor.fetchall()

    level_thresholds = {row["level"]: row["min"] for row in level_data}

    # Determine new level
    new_level = current_level
    for level, min in level_thresholds.items():
        if xp >= min:
            new_level = level
        else:
            break  # Stop checking once we reach a level they don't qualify for

    # If the level increased, apply upgrade
    if new_level > current_level:
        cursor.execute("UPDATE squires SET level = %s WHERE id = %s", (new_level, squire_id))
        conn.commit()
        session.message=[f"\n🎉 Congratulations! You leveled up to Level {new_level}!"]

    cursor.close()


def get_inventory(squire_id, conn):
    """Display all items the player has collected."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("""
        SELECT item_name, item_type, description, sum(uses_remaining) as uses_remaining, count(*) as effect FROM inventory
        WHERE squire_id = %s group by item_name, item_type, description ORDER BY item_type, item_name
    """, (squire_id,))

    items = cursor.fetchall()
    cursor.close()

    return items

def get_hunger_bar(squire_id, conn):
    """Generates a hunger bar displaying food status."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Count total food uses remaining in inventory
    cursor.execute("""
        SELECT COALESCE(SUM(uses_remaining), 0) AS total_uses
        FROM inventory WHERE squire_id = %s and item_type = 'food'
    """, (squire_id,))

    total_uses = cursor.fetchone()["total_uses"]

    # Convert Decimal to integer
    total_uses = int(total_uses) if isinstance(total_uses, decimal.Decimal) else total_uses

    cursor.close()

    # Define the number of "Full" vs "Hungry" icons
    full_count = min(total_uses, 8)  # Max 8 full icons
    hunger_count = 8 - full_count

    # Create the hunger bar
    hunger_bar = " ".join(["🟩"] * full_count + ["🟥"] * hunger_count)

    return hunger_bar

def check_quest_progress(squire_id, quest_id, conn):
    """Calculates and returns the player's progress in the current quest."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Count the total number of riddles required for quest completion
    cursor.execute("SELECT COUNT(*) AS total FROM riddles WHERE difficulty = 'hard' and quest_id = %s", (quest_id,))
    total_riddles = cursor.fetchone()["total"] + 6

    # Count how many the squire has answered
    cursor.execute("""
        SELECT COUNT(*) AS answered FROM squire_riddle_progress
        WHERE squire_id = %s AND quest_id = %s AND answered_correctly = TRUE
    """, (squire_id, quest_id))
    answered_riddles = cursor.fetchone()["answered"]

    cursor.close()

    # Calculate completion percentage
    progress_percentage = (answered_riddles / total_riddles) * 100 if total_riddles > 0 else 0

    return answered_riddles, total_riddles, progress_percentage

def display_progress_bar(percentage):
    """Generates a text-based progress bar."""
    bar_length = 20  # Number of segments in the bar
    filled_length = int(bar_length * (percentage / 100))
    bar = "█" * filled_length + "-" * (bar_length - filled_length)

    return f"[{bar}] {percentage:.1f}% Complete"

#town work functions
def display_hall_of_fame(conn):
    """Displays the Hall of Fame with the top XP players."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch top 10 players sorted by XP
    cursor.execute("""
        SELECT squire_name, experience_points
        FROM squires
        ORDER BY experience_points DESC
        LIMIT 10
    """)

    top_players = cursor.fetchall()
    cursor.close()

    # Format and display the leaderboard
    print("\n🏆 **Hall of Fame - Top Adventurers** 🏆")
    print("-" * 40)
    print(f"{'Rank':<5}{'Squire':<20}{'XP':>10}")
    print("-" * 40)

    if not top_players:
        print("No legendary adventurers yet! Be the first to claim glory!")
    else:
        for rank, player in enumerate(top_players, start=1):
            print(f"{rank:<5}{player['squire_name']:<20}{player['experience_points']:>10}")

    print("-" * 40)

def visit_town_for_work(squire_id, conn):
    """Allows players to take on town jobs to earn gold."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch available jobs
    cursor.execute("SELECT id, job_name, description, min_payout, max_payout FROM jobs")
    jobs = cursor.fetchall()

    print("\n🏛 Welcome to the Town Office! Here are the available jobs:")
    for job in jobs:
        print(f"  [{job['id']}] {job['job_name']} - {job['description']} (💰 Pays {job['min_payout']} to {job['max_payout']} bits)")

    choice = input("\nEnter the job ID to take or 'Q' to exit: ").strip().upper()

    if choice == "Q":
        print("🏛 You leave the Town Office.")
        return

    try:
        job_id = int(choice)

        # Fetch job details
        cursor.execute("SELECT job_name, min_payout, max_payout FROM jobs WHERE id = %s", (job_id,))
        job = cursor.fetchone()

        if not job:
            print("❌ Invalid selection.")
            return

        # Generate a random gold payout within the range
        payout = random.randint(job["min_payout"], job["max_payout"])

        # Update player's gold
        cursor.execute("UPDATE teams SET gold = gold + %s WHERE id = (SELECT team_id FROM squires WHERE id = %s)", (payout, squire_id))
        conn.commit()

        print(f"✅ You completed '{job['job_name']}' and earned 💰 {payout} bits!")

    except ValueError:
        print("❌ Invalid input. Please enter a valid job ID.")

    cursor.close()

#quest & riddle related actions

def update_riddle_hints(conn):
    """Updates the word length hints for all riddles in the database."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch all riddles and their answers
    cursor.execute("SELECT id, answer FROM riddles where word_length_hint is null OR word_count is null")
    riddles = cursor.fetchall()

    for riddle in riddles:
        riddle_id = riddle["id"]
        answer = riddle["answer"]
        hint = generate_word_length_hint(answer)
        wc = generate_word_count(answer)

        # Update the riddle with the generated hint
        cursor.execute("UPDATE riddles SET word_length_hint = %s, word_count = %s WHERE id = %s", (hint, wc, riddle_id))

    conn.commit()
    cursor.close()
    message = "✅ Riddle hints updated successfully!"

    return message

def generate_word_length_hint(answer):
    """Generates a hint based on the number of characters in each word of the answer."""
    words = answer.split()  # Split the answer into words
    hint = " ".join(str(len(word)) for word in words)  # Replace each word with its length
    return hint

def generate_word_count(answer):
    word_count = len(answer.split())
    return word_count

def save_correct_answer(squire_id, quest_id, riddle_id, conn):
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("""
    INSERT INTO squire_riddle_progress (squire_id, riddle_id, quest_id, answered_correctly)
    VALUES (%s, %s, %s, TRUE)
    """, (squire_id, riddle_id, quest_id))

    conn.commit()
    cursor.close()

def check_quest_completion(squire_id, quest_id, conn):
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    if session.get("boss_defeated"):
        return True

    # Count the total riddles required for quest completion (ensure Hard ones are included)
    cursor.execute("SELECT COUNT(*) AS total FROM riddles WHERE difficulty = 'hard' AND quest_id = %s", (quest_id,))
    total_riddles = cursor.fetchone()["total"] + 6

    # Count how many the squire has answered
    cursor.execute("""
        SELECT COUNT(*) AS answered FROM squire_riddle_progress
        WHERE squire_id = %s AND quest_id = %s AND answered_correctly = TRUE
    """, (squire_id, quest_id))
    answered_riddles = cursor.fetchone()["answered"]

    cursor.close()

    return answered_riddles >= total_riddles  # Only complete when all are done

def complete_quest(squire_id, quest_id, conn):
    """Handles quest completion: Grants rewards, marks the quest complete, and unlocks the next quest."""

    if check_quest_completion(squire_id, quest_id, conn):
        messages = ["\n🎉 Congratulations! You have completed this quest!"]

        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # Fetch the quest reward
        cursor.execute("SELECT reward, effective_against FROM quests WHERE id = %s", (quest_id,))
        row = cursor.fetchone()

        if row:
            reward_item, effective_against = row["reward"], row["effective_against"]

            # Grant the special item
            cursor.execute("""
                INSERT INTO inventory (squire_id, item_name, description, item_type, effective_against)
                VALUES (%s, %s, %s, %s, %s)
            """, (squire_id, reward_item, f"Special reward for completing quest {quest_id}.", 'special', effective_against))
            messages.append(f"🏆 You have received a special item: {reward_item}!")

        conn.commit()

        # Clear travel history for this player
        cursor.execute("DELETE FROM travel_history WHERE squire_id = %s", (squire_id,))
        conn.commit()

        # Mark quest as "completed" (avoiding duplicate errors)
        cursor.execute("""
            INSERT INTO squire_quest_status (squire_id, quest_id, status)
            VALUES (%s, %s, 'completed')
            ON DUPLICATE KEY UPDATE status = 'completed'
        """, (squire_id, quest_id))
        conn.commit()

        # Unlock a new quest dynamically
        cursor.execute("""
            SELECT id FROM quests WHERE id > %s ORDER BY id ASC LIMIT 1
        """, (quest_id,))
        next_quest = cursor.fetchone()

        if next_quest:
            cursor.execute("""
                UPDATE quests SET status='active' WHERE id = %s
            """, (next_quest["id"],))
            conn.commit()
            messages.append(f"🛡️ A new quest has been unlocked: Quest {next_quest['id']}!")
        else:
            messages.append("⚠️ No more quests available!")

        cursor.close()
        session["quest_message"] = messages

        return True  # ✅ Indicate that the quest was successfully completed

    else:
        session["quest_message"] = ("\n🔎 You still have more riddles to solve in this quest!")
        return False  # ✅ Indicate that the quest is not yet complete


def get_random_riddle(quest_id, squire_id, conn):
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Count how many riddles the squire has answered correctly for this quest
    cursor.execute("""
        SELECT COUNT(*) AS answered FROM squire_riddle_progress
        WHERE squire_id = %s AND quest_id = %s AND answered_correctly = TRUE
    """, (squire_id, quest_id))
    answered_riddles = cursor.fetchone()["answered"]

    # Determine difficulty based on progress
    if answered_riddles < 3:
        difficulty = "Easy"
    elif answered_riddles < 6:
        difficulty = "Medium"
    else:
        difficulty = "Hard"

    # Fetch an unanswered riddle of the chosen difficulty
    query = """
    SELECT id, riddle_text, difficulty, answer, hint, word_length_hint FROM riddles
    WHERE quest_id = %s AND difficulty = %s
    AND id NOT IN (SELECT riddle_id FROM squire_riddle_progress WHERE squire_id = %s)
    ORDER BY RAND() LIMIT 1
    """

    cursor.execute(query, (quest_id, difficulty, squire_id))
    riddle = cursor.fetchone()


    cursor.close()
    return riddle  # Returns None if no unanswered riddles remain

def encounter_riddle(quest_id, squire_id, conn):
    riddle = get_random_riddle(quest_id, squire_id, conn)

    r = None

    if not riddle:
        r = "🏆 You've mastered all riddles for this quest! No more questions remain."
        return r

    print(f"\n📜 Riddle ({riddle['difficulty']}): {riddle['riddle_text']}")

    c = conn.cursor()
    c.execute("SELECT count(*) as magic from INVENTORY where squire_id = %s and item_name like %s ",(squire_id, "%Lexicon%"))
    result = c.fetchone()
    magic = result["magic"] if result else 0  # Default to 0 if result is None
    logging.debug(f"Test for Lexicon in Inventory: {magic}")

    if magic > 0:
        print(f"💡 Clue: {riddle['word_length_hint']} (Number of letters in each word)")
    c.close()

    answer = input("Enter your answer: ").strip().lower()

    if answer == riddle['answer'].strip().lower():
        r = "✅ Correct! You gain experience."

        # Adjust XP and gold rewards based on difficulty
        xp_reward = 10 if riddle["difficulty"] == "Easy" else 20 if riddle["difficulty"] == "Medium" else 30
        gold_reward = 5 if riddle["difficulty"] == "Easy" else 15 if riddle["difficulty"] == "Medium" else 50

        r += f"You gain {xp_reward} XP and {gold_reward} bits!"
        update_squire_progress(squire_id, conn, xp_reward, gold_reward)

        # Save progress
        save_correct_answer(squire_id, quest_id, riddle['id'], conn)


    else:
        r = f"❌ Incorrect! Hint: {riddle['hint']}"

    return r

def check_riddle_answer(user_answer, riddle_id, conn):
    cursor=conn.cursor()
    cursor.execute("SELECT answer FROM riddles WHERE id = %s", (riddle_id,))
    correct_answer = cursor.fetchone()

    if correct_answer and user_answer.lower().strip() == correct_answer[0].lower().strip():
        print("✅ Correct! You unlocked the chest!")
        return True
    else:
        print("❌ Incorrect! Try again.")
        return False

def get_active_quests(conn, squire_id):
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute(f"""
    SELECT id, quest_name, description FROM quests WHERE
    id not in (select distinct quest_id from squire_quest_status where squire_id={squire_id} and status = 'completed')
    ORDER BY id LIMIT 1;
    """)
    quests = cursor.fetchall()

    return quests

# Display available quests
def chooseq(conn, squire_id):
    quests = get_active_quests(conn, squire_id)

    print("\n🏰 Available Quests:")
    for q in quests:
        print(f"[{q['id']}] {q['quest_name']}: {q['description']}")

    quest_id = int(input("\nEnter the Quest ID to embark on your journey: "))
    return quest_id

def get_riddles_for_quest(quest_id, conn):
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT id, riddle_text, answer, hint FROM riddles WHERE quest_id = %s", (quest_id,))
    riddles = cursor.fetchall()

    return riddles

# shop related functions
def visit_shop(squire_id, level, conn):
    """Allows players to buy food & drinks using gold."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch available items
    cursor.execute(f"SELECT id, item_name, description, price, uses, item_type FROM shop_items where min_level <= {level}")
    items = cursor.fetchall()

    print("\n🛒 Welcome to the Bit Mall! Here's what we have:")
    for item in items:
        print(f"  [{item['id']}] {item['item_name']} - {item['description']} (💰 {item['price']} bits, 🍴 {item['uses']} uses)")

    # Get player's current gold
    cursor.execute("SELECT t.gold FROM squires s JOIN teams t ON s.team_id = t.id WHERE s.id = %s", (squire_id,))
    player_gold = cursor.fetchone()["gold"]

    print(f"\n💰 You have {player_gold} Bitcoin.")
    choice = input("Enter the item ID to buy or 'Q' to exit: ").strip().upper()

    if choice == "Q":
        print("🏪 You leave the shop.")
        return

    try:
        item_id = int(choice)

        # Fetch the item price and details
        cursor.execute("SELECT item_name, price, uses, item_type FROM shop_items WHERE id = %s", (item_id,))
        item = cursor.fetchone()

        if not item:
            print("❌ Invalid selection.")
            return

        if player_gold < item["price"]:
            print("❌ You don't have enough gold!")
            return

        # Deduct gold and add the item to inventory
        cursor.execute("UPDATE teams SET gold = gold - %s WHERE id = (SELECT team_id FROM squires WHERE id = %s)", (item["price"], squire_id))
        cursor.execute("INSERT INTO inventory (squire_id, item_name, description, item_type, uses_remaining) VALUES (%s, %s, %s, %s, %s)",
                       (squire_id, item["item_name"], f"{item['uses']} uses left", item["item_type"], item["uses"]))

        conn.commit()
        print(f"✅ You bought {item['item_name']}!")

    except ValueError:
        print("❌ Invalid input. Please enter a valid item ID.")

    cursor.close()

def consume_food(squire_id, conn):
    """Uses up food from inventory when traveling."""

    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Get player's level
    cursor.execute("SELECT level FROM squires WHERE id = %s", (squire_id,))
    level = cursor.fetchone()["level"]

    # Find an available food item
    cursor.execute("SELECT id, item_name, uses_remaining FROM inventory WHERE squire_id = %s AND item_type = 'food' AND uses_remaining > 0 LIMIT 1", (squire_id,))
    food = cursor.fetchone()

     # Define hunger reduction chances based on level
    hunger_reduction = {1: 0, 2: 10, 3: 25, 4: 50, 5: 75}  # % chance to avoid hunger
    avoid_hunger_chance = hunger_reduction.get(level, 0)

    # Random roll to determine if food is consumed
    if random.randint(1, 100) <= avoid_hunger_chance:
        message = f"🌟 Your experience helps you travel efficiently! You avoid hunger this time."
        cursor.close()
        return True, message  # Skip food consumption

    if not food:
        message = "🚫 No food available! You feel the pangs of hunger."
        cursor.close()
        return False, message  # Prevent movement

    # Reduce the remaining uses
    new_uses = food["uses_remaining"] - 1
    if new_uses == 0:
        cursor.execute("DELETE FROM inventory WHERE id = %s", (food["id"],))  # Remove empty items
        message = f"🗑️ You finished your {food['item_name']}."

    else:
        cursor.execute("UPDATE inventory SET uses_remaining = %s WHERE id = %s", (new_uses, food["id"]))
        message = f"🍽️ You used your {food['item_name']}. Remaining uses: {new_uses}."

    conn.commit()
    cursor.close()
    return True, message
