import random
import pymysql
import logging
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

def insert_treasure_chests(conn, quest_id, squire_quest_id):

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # Fetch related riddles
        cursor.execute("SELECT id, difficulty FROM riddles WHERE quest_id = %s AND id not in (select riddle_id from treasure_chests WHERE squire_quest_id = %s)",(quest_id,squire_quest_id))
        riddles = cursor.fetchall()

        for riddle in riddles:
            riddle_id = riddle["id"]
            difficulty = riddle["difficulty"]

            # Generate randomized values based on difficulty
            x, y = generate_random_coordinates(difficulty)
            gold, xp, food, special_item = generate_rewards(difficulty)

            # Insert the treasure chest into the database
            cursor.execute("""
                INSERT INTO treasure_chests (x_coordinate, y_coordinate, riddle_id, gold_reward, xp_reward, food_reward, special_item, squire_quest_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (x, y, riddle_id, gold, xp, food, special_item, squire_quest_id))

            try:
                conn.commit()
                message = "✅ Treasure chests inserted successfully!"

            except Exception as e:
                logging.warning(f"There was an error {e} inserting new treasure chests for {quest_id} on {squire_quest_id} quest.")
                message = "No new treasure chests created for this quest, Squire."

        return message

    except Exception as e:
        logging.warning(f"There was an error inserting new treasure chests {e}")


def generate_terrain_features_dynamic(
    conn, squire_id, squire_quest_id,
    num_forest_clusters=5, cluster_size=10, max_forests=75,
    num_mountain_ranges=3, mountain_range_length=9, max_mountains=45
):
    try:
        cursor = conn.cursor()

        # Fetch squire level
        cursor.execute("SELECT level FROM squires WHERE id = %s", (squire_id,))
        level = cursor.fetchone()[0]

        # Dynamic placement radius
        placement_radius = 10 + level * 2
        map_center = (0, 0)

        # Fetch restricted tiles
        cursor.execute("SELECT x_coordinate, y_coordinate FROM map_features WHERE squire_id = %s", (squire_id,))
        restricted = set(cursor.fetchall())

        cursor.execute("""
            SELECT x_coordinate, y_coordinate FROM treasure_chests
            WHERE squire_quest_id = %s AND is_opened = FALSE
        """, (squire_quest_id,))
        restricted.update(cursor.fetchall())
        restricted.update([(40, 40), (0, 0)])

        forests = set()
        mountains = set()
        river = []

        # Generate river if not present
        cursor.execute("SELECT COUNT(*) FROM map_features WHERE squire_id = %s AND terrain_type = 'river'", (squire_id,))
        river_exists = cursor.fetchone()[0]

        if river_exists == 0:
            river_start_x = map_center[0] - placement_radius
            river_start_y = map_center[1] + random.randint(-placement_radius, placement_radius)
            x, y = river_start_x, river_start_y
            for _ in range(25 + level * 2):
                if (x, y) not in restricted:
                    river.append((x, y, squire_id))
                    restricted.add((x, y))
                x += 1
                y += random.choice([-1, 0, 1])

        # Generate forest clusters
        cursor.execute("SELECT COUNT(*) FROM map_features WHERE squire_id = %s AND terrain_type = 'forest'", (squire_id,))
        existing_forests = cursor.fetchone()[0]
        forests_needed = max_forests - existing_forests

        for _ in range(min(num_forest_clusters, forests_needed // cluster_size)):
            cx = random.randint(map_center[0] - placement_radius, map_center[0] + placement_radius)
            cy = random.randint(map_center[1] - placement_radius, map_center[1] + placement_radius)

            for _ in range(cluster_size):
                fx = cx + random.randint(-2, 2)
                fy = cy + random.randint(-2, 2)
                if (fx, fy) not in restricted:
                    forests.add((fx, fy, squire_id))
                    restricted.add((fx, fy))
                if len(forests) >= forests_needed:
                    break

        # Generate mountain ranges
        cursor.execute("SELECT COUNT(*) FROM map_features WHERE squire_id = %s AND terrain_type = 'mountain'", (squire_id,))
        existing_mountains = cursor.fetchone()[0]
        mountains_needed = max_mountains - existing_mountains

        for _ in range(min(num_mountain_ranges, mountains_needed // mountain_range_length)):
            mx = random.randint(map_center[0] - placement_radius, map_center[0] + placement_radius)
            my = random.randint(map_center[1] - placement_radius, map_center[1] + placement_radius)
            horizontal = random.choice([True, False])
            for i in range(mountain_range_length):
                x = mx + (i if horizontal else 0)
                y = my + (0 if horizontal else i)
                if (x, y) not in restricted:
                    mountains.add((x, y, squire_id))
                    restricted.add((x, y))
                if len(mountains) >= mountains_needed:
                    break

        # Insert into map_features
        if river:
            cursor.executemany("INSERT INTO map_features (x_coordinate, y_coordinate, squire_id, terrain_type) VALUES (%s, %s, %s, 'river')", river)
        if forests:
            cursor.executemany("INSERT INTO map_features (x_coordinate, y_coordinate, squire_id, terrain_type) VALUES (%s, %s, %s, 'forest')", list(forests))
        if mountains:
            cursor.executemany("INSERT INTO map_features (x_coordinate, y_coordinate, squire_id, terrain_type) VALUES (%s, %s, %s, 'mountain')", list(mountains))

        conn.commit()
        cursor.close()
    except Exception as e:
        print("🔥 TERRAIN ERROR:", e)

def generate_terrain_features(conn, squire_id, squire_quest_id, num_forest_clusters=5, cluster_size=10, max_forests=75,
                              num_mountain_ranges=3, mountain_range_length=9, max_mountains=45):

    try:
        logging.debug("🌍 generate_terrain_features called for squire_id %s", squire_id)
        rivers_to_insert=False

        """Generates random forest clusters and mountain ranges and inserts them into the map_features table."""
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # ✅ Check existing forests in the database
        cursor.execute("SELECT COUNT(id) as existingtrees FROM map_features WHERE terrain_type = 'forest' and squire_id=%s",(squire_id,))
        existing_forest_count = cursor.fetchone()["existingtrees"]

        if existing_forest_count >= max_forests:
            logger.warning("✅ No new forests added. Map already has enough trees!")

        # ✅ Check existing mountains in the database
        cursor.execute("SELECT COUNT(id) as existingmountains FROM map_features WHERE terrain_type = 'mountain' and squire_id=%s",(squire_id,))
        existing_mountain_count = cursor.fetchone()["existingmountains"]

        if existing_mountain_count >= max_mountains:
            logger.warning("✅ No new mountains added. Map already has enough mountains!")

        # ✅ Fetch existing map features to avoid placing forests/mountains in special locations
        cursor.execute("SELECT x_coordinate, y_coordinate FROM map_features WHERE squire_id=%s",(squire_id,))
        existing_features = { (row["x_coordinate"], row["y_coordinate"]) for row in cursor.fetchall() }

        # ✅ Fetch treasure chest locations to avoid placing terrain on them
        cursor.execute("SELECT T.x_coordinate, T.y_coordinate FROM treasure_chests T WHERE T.is_opened = FALSE and T.squire_quest_id=%s",(squire_quest_id,))
        chest_locations = { (row["x_coordinate"], row["y_coordinate"]) for row in cursor.fetchall() }

        all_restricted_locations = existing_features | chest_locations | {(0, 0), (40,40)}  # Avoid placing forests/mountains at the village
        logger.debug(f"{all_restricted_locations}")

        forests_to_insert = set()  # Store forests before inserting into DB
        mountains_to_insert = set()  # Store mountains before inserting into DB

        cursor.execute("""
            SELECT level from squires where id = %s
        """, (squire_id,))
        l = cursor.fetchone()
        level = l["level"]

        # ✅ Check existing mountains in the database
        cursor.execute("SELECT COUNT(id) as existingriver FROM map_features WHERE terrain_type = 'river' and squire_id=%s",(squire_id,))
        existing_river_count = cursor.fetchone()["existingriver"]

        planned_river_length = 25 + level * 2

        if existing_river_count >= planned_river_length:
            logger.warning("✅ No new rivers added. Map already has enough rivers!")
        else:
            rivers_to_insert = True
            # ✅ Generate a river that avoids existing features
            river_length = 25 + level * 2  # grow river as quest ID increases
            river_start = (-40, random.randint(-10, 10))  # start on far left side

            river_path = generate_river_path(
                start_x=river_start[0],
                start_y=river_start[1],
                length=river_length,
                bendiness=0.7,
                restricted=set(all_restricted_locations)  # prevent overlaps
            )

            # ✅ Mark river path as restricted so forest/mountains avoid it
            for coord in river_path:
                all_restricted_locations.add(coord)


        # ✅ Place the stronghold at (40,40) if not already placed
        cursor.execute("SELECT COUNT(*) as count FROM map_features WHERE x_coordinate = 40 AND y_coordinate = 40 AND terrain_type = 'stronghold' and squire_id=%s",(squire_id,))
        if cursor.fetchone()["count"] == 0:
            cursor.execute("INSERT INTO map_features (x_coordinate, y_coordinate, squire_id, terrain_type) VALUES (40, 40, %s, 'stronghold')", (squire_id,))
            logger.debug("🏰 Stronghold placed at (40,40)")

        # ✅ Surround the stronghold with forests (e.g., a 3-tile radius)
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx == 0 and dy == 0:
                    continue  # Skip the stronghold's location
                new_x, new_y = 40 + dx, 40 + dy
                if (new_x, new_y) not in all_restricted_locations:
                    forests_to_insert.add((new_x, new_y, squire_id))
        logger.debug(f"🌲 Surrounding forests planned: {len(forests_to_insert)} locations")


        # ✅ Generate Forest Clusters
        forests_needed = max_forests - existing_forest_count
        clusters_needed = min(num_forest_clusters, forests_needed // cluster_size)

        for _ in range(clusters_needed):
            center_x = random.randint(-30, 30)
            center_y = random.randint(-30, 30)

            while (center_x, center_y) in all_restricted_locations:
                center_x = random.randint(-30, 30)
                center_y = random.randint(-30, 30)

            for _ in range(cluster_size):
                offset_x = random.randint(-2, 2)  # Small offset for clustering
                offset_y = random.randint(-2, 2)

                new_x = center_x + offset_x
                new_y = center_y + offset_y

                if (new_x, new_y) not in all_restricted_locations and (new_x, new_y) not in forests_to_insert:
                    forests_to_insert.add((new_x, new_y, squire_id))

                if len(forests_to_insert) >= forests_needed:
                    break

        # ✅ Generate Mountain Ranges
        mountains_needed = max_mountains - existing_mountain_count
        ranges_needed = min(num_mountain_ranges, mountains_needed // mountain_range_length)

        for _ in range(ranges_needed):
            start_x = random.randint(-45, 45)
            start_y = random.randint(-45, 45)

            while (start_x, start_y) in all_restricted_locations:
                start_x = random.randint(-45, 45)
                start_y = random.randint(-45, 45)

            # ✅ Choose a direction for the mountain range (horizontal or vertical)
            is_horizontal = random.choice([True, False])

            for i in range(mountain_range_length):
                new_x = start_x + (i if is_horizontal else 0)
                new_y = start_y + (0 if is_horizontal else i)

                if (new_x, new_y) not in all_restricted_locations and (new_x, new_y) not in mountains_to_insert:
                    mountains_to_insert.add((new_x, new_y, squire_id))

                if len(mountains_to_insert) >= mountains_needed:
                    break

        # ✅ Convert set of coordinates to a list of tuples before inserting
        if forests_to_insert:
            forests_list = [(x, y, squire_id) for x, y, squire_id in forests_to_insert]  # ✅ Convert set to list of tuples
            cursor.executemany("INSERT INTO map_features (x_coordinate, y_coordinate,  squire_id, terrain_type) VALUES (%s, %s,  %s, 'forest')", forests_list)
            logger.debug(f"✅ {len(forests_to_insert)} forest locations added.")

        if mountains_to_insert:
            mountains_list = [(x, y, squire_id) for x, y,squire_id in mountains_to_insert]  # ✅ Convert set to list of tuples
            cursor.executemany("INSERT INTO map_features (x_coordinate, y_coordinate, squire_id, terrain_type) VALUES (%s, %s, %s, 'mountain')", mountains_list)
            logger.debug(f"🏔️ {len(mountains_to_insert)} mountain locations added.")

        if rivers_to_insert:
            river_list = [(x, y, squire_id) for x, y in river_path]
            cursor.executemany(
                "INSERT INTO map_features (x_coordinate, y_coordinate, squire_id, terrain_type) VALUES (%s, %s, %s, 'river')",
                river_list
            )
            logger.debug(f"🌊 {len(river_list)} river tiles added.")


        conn.commit()
        cursor.close()
    except Exception as e:
        logging.warning(f"Error generating terrain features {e}")
        print("🔥 TERRAIN ERROR:", e)

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



def generate_forest_clusters(conn, num_clusters=5, cluster_size=10, max_forests=50):
    """Generates random forest clusters and inserts them into the map_features table."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT COUNT(id) as existingtrees from map_features where terrain_type = 'forest'")
    existing_forest_count = cursor.fetchone()["existingtrees"]

    if existing_forest_count >= max_forests:
        logging.debug("✅ No new forests added. Map already has enough trees!")
        cursor.close()
        return

    # Calculate how many forests we still need to add
    forests_needed = max_forests - existing_forest_count
    clusters_needed = min(num_clusters, forests_needed // cluster_size)

    # Fetch existing map features to avoid placing forests in special locations
    cursor.execute("SELECT x_coordinate, y_coordinate FROM map_features")
    existing_features = { (row["x_coordinate"], row["y_coordinate"]) for row in cursor.fetchall() }

    # Fetch treasure chest locations to avoid placing forests on them
    cursor.execute("SELECT x_coordinate, y_coordinate FROM treasure_chests WHERE is_opened = FALSE")
    chest_locations = { (row["x_coordinate"], row["y_coordinate"]) for row in cursor.fetchall() }

    all_restricted_locations = existing_features | chest_locations | {(0, 0)}  # Avoid placing forests at the village

    forests_to_insert = set()  # Store forests before inserting into DB

    for _ in range(clusters_needed):
        # Pick a random center for the forest
        center_x = random.randint(-15, 15)
        center_y = random.randint(-15, 15)

        # Ensure the center is not on a restricted location
        while (center_x, center_y) in all_restricted_locations:
            center_x = random.randint(-15, 15)
            center_y = random.randint(-15, 15)

        # Generate a clustered forest around the center point
        for _ in range(cluster_size):
            offset_x = random.randint(-2, 2)  # Small random offset to cluster trees
            offset_y = random.randint(-2, 2)

            new_x = center_x + offset_x
            new_y = center_y + offset_y

            # Ensure we don't place duplicate trees or overwrite restricted spots
            if (new_x, new_y) not in all_restricted_locations and (new_x, new_y) not in forests_to_insert:
                forests_to_insert.add((new_x, new_y))

            if len(forests_to_insert) >= forests_needed:
                break
    if forests_to_insert:
        # Insert forests into the map_features table
        cursor.executemany("INSERT INTO map_features (x_coordinate, y_coordinate, terrain_type) VALUES (%s, %s, 'forest')", list(forests_to_insert))
        conn.commit()
        cursor.close()

    print(f"✅ {len(forests_to_insert)} forest locations added.")
