from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import pymysql
import random
import logging
import socks
import socket
from urllib.parse import urlparse
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool
import os
import re
import requests
from dotenv import load_dotenv

# Configure logging based on environment
def setup_logging():
    # Get log level from environment variable, default to INFO
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()

    # Create a formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Always log to stdout for Heroku
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    # Configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(stream_handler)

    # If we're in development, also log to a file
    if os.getenv('FLASK_ENV') == 'development':
        try:
            file_handler = logging.FileHandler('debug.log')
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
            logging.info('File logging enabled in development mode')
        except Exception as e:
            logging.warning(f'Could not set up file logging: {e}')

    # Quiet some of the noisier libraries
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

# Set up logging when the app starts
setup_logging()

from shared import get_squire_stats
from shared import check_quest_completion
from shared import complete_quest
from shared import get_random_riddle
from shared import check_riddle_answer
from shared import get_active_quests
from shared import chooseq
from shared import get_riddles_for_quest
from shared import update_squire_progress
from shared import get_inventory
from shared import visit_shop
from shared import consume_food
from shared import get_hunger_bar
from shared import update_player_position
from shared import check_for_treasure
from shared import open_treasure_chest
from shared import check_quest_progress
from shared import display_progress_bar
from shared import generate_word_length_hint
from shared import update_riddle_hints
from init import insert_treasure_chests
from shared import display_travel_map
from shared import display_hall_of_fame
from init import generate_terrain_features
from shared import check_for_treasure_at_location
from shared import calculate_hit_chance
from shared import can_enter_tile
from shared import get_viewport_map
from shared import calculate_enemy_encounter_probability
from shared import update_work_for_combat
from shared import get_player_max_hunger
from shared import mod_enemy_hunger
from shared import calculate_riddle_reward

from shared import combat_mods
from shared import hunger_mods
from shared import degrade_gear
from shared import ishint
from shared import iswordcounthint
from shared import iswordlengthhint
from shared import flee_safely
from shared import calc_flee_safely
#from flask_socketio import SocketIO, emit, join_room

# Load environment variables at the start of the application
load_dotenv()

#this is intended to pool connections to the proxy for MySQL and reduce the number of connections initiated

fixie_url = os.getenv("QUOTA_GUARD_HOST")
recaptcha = os.getenv("RECAPTCHA_SECRET_KEY")

parsed = urlparse(f"https://{fixie_url}")
proxy_host = parsed.hostname
proxy_port = parsed.port
proxy_user = parsed.username
proxy_pass = parsed.password

#print(f"{fixie_url}")
socks.set_default_proxy(
    socks.SOCKS5,
    proxy_host,
    proxy_port,
    True,
    proxy_user,
    proxy_pass
)
socket.socket = socks.socksocket  # Monkey patch

# Build DB URI for SQLAlchemy
DB_URI = f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}"

# Create engine with connection pool
engine = create_engine(
    DB_URI,
    connect_args={
        "ssl": {"ssl": {}}  # Minimal SSL context; Azure may require it
    },
    poolclass=QueuePool,
    pool_size=5,         # Adjust as needed
    max_overflow=10,     # Extra connections if pool is full
    pool_timeout=30,     # Seconds to wait for connection
    pool_recycle=1800    # Recycle connections every 30 min
)

#"cursorclass": pymysql.cursors.DictCursor,

app = Flask(__name__)
app.config["DEBUG"] = True
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your_secret_key')  # For session management

# Database connection function
def get_db_connection():

    try:
        conn = engine.raw_connection()
        return conn

    except Exception as e:
        logging.error(f"Database connection error: {str(e)}")
        raise

def add_team_message(team_id, message, db):
    cursor = db.cursor(pymysql.cursors.DictCursor)
    cursor.execute(
        "INSERT INTO team_messages (team_id, message) VALUES (%s, %s)",
        (team_id, message)
    )
    db.commit()

def calculate_feature_counts(level, quest_id, base_trees=75, base_mountains=50):
    # Example formula: scale trees and mountains with level and quest
    tree_multiplier = 1 + (level * 0.1) + (quest_id * 0.05)
    mountain_multiplier = 1 + (level * 0.08) + (quest_id * 0.07)

    tree_count = int(base_trees * tree_multiplier)
    mountain_count = int(base_mountains * mountain_multiplier)

    return tree_count, mountain_count

def is_valid_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

if __name__ == '__main__':
    app.run(port=5050)

#socketio = SocketIO(app)

# 🏠 Homepage (Start Game)
@app.route("/")
def home():
    return render_template("index.html")

#@socketio.on('join')
#def handle_join(data):
#    join_room(f"team_{data['team_id']}")

#def broadcast_team_message(team_id, message):
#    socketio.emit('team_message', {'message': message}, room=f"team_{team_id}")

@app.route("/team_messages/<int:team_id>")
def get_team_messages(team_id):
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    since = request.args.get("since", None)  # Timestamp of last check


    if since:
        try:
            clean_since = since.split('.')[0].replace('T', ' ')
            #print(f"{clean_since}")
            query = """
                SELECT message, created_at FROM team_messages
                WHERE team_id = %s AND created_at > %s
                ORDER BY created_at ASC
            """
            cursor.execute(query, (team_id, clean_since))
        except Exception as e:
            logging.debug("Timestamp parsing error:", e)
            return jsonify([ ])

    else:
        query = """
        SELECT id, message, created_at FROM team_messages
        WHERE team_id = %s ORDER BY created_at DESC
        LIMIT 1
    """
        cursor.execute(query, (team_id, ))

    rows = cursor.fetchall()
    return jsonify(rows)

@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    return render_template('index.html')

@app.route('/getting_started')
def getting_started():
    return render_template('getting_started.html')

@app.route('/npc', methods=['GET'])
def npc():
    """Handles NPC encounters and displays hints."""
    npc_message = session.pop("npc_message", "The trader has no hints for you.")
    logging.debug(f"NPC Page Loaded - Message: {npc_message}")  # Debugging
    return render_template("npc.html", npc_message=npc_message)

@app.route('/select_course/<int:course_id>', methods=['GET'])
def select_course(course_id):
    """Sets the selected course and redirects to quest selection."""

    session["course_id"] = course_id

    #print(f"🚀 DEBUG: Selected course_id set in session → {session.get('course_id', 'NOT SET')}")
    return redirect(url_for('quest_select'))  # ✅ Refresh quest selection page


# 🔑 Login (Enter Squire ID)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        squire = request.form['squire_id']
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        cursor.execute("SELECT id, squire_name, team_id FROM squires WHERE squire_name = %s", (squire,))
        squire = cursor.fetchone()

        if squire:
            session['squire_id'] = squire['id']
            session['squire_name'] = squire['squire_name']
            session['team_id'] = squire['team_id']


            update_riddle_hints(conn)

            return redirect(url_for("quest_select"))  # ✅ Redirect

    return render_template('index.html')

@app.route("/register", methods=["GET", "POST"])
def register_squire():
    if request.method == "POST":
        squire_name = request.form["squire_name"]
        real_name = request.form["real_name"]
        email = request.form["email"]
        captcha_response = request.form.get("g-recaptcha-response")
        team_id = int(request.form["team_id"])

        # Email format check
        if not is_valid_email(email):
            flash("Invalid email format.")
            return redirect(url_for("register_squire"))

        print("🌱 FORM DATA:", squire_name, real_name, email, team_id)

        # Validate inputs
        if not squire_name or not real_name or not email or not team_id:
            flash("🚫 Please fill out all required fields.")
            return redirect(url_for("register_squire"))

        # Verify CAPTCHA
        captcha_verify_url = "https://www.google.com/recaptcha/api/siteverify"
        response = requests.post(captcha_verify_url, data={
            'secret': recaptcha,
            'response': captcha_response
        })
        result = response.json()

        # After CAPTCHA result:
        print("✅ CAPTCHA result:", result)

        if not result.get("success"):
            flash("CAPTCHA verification failed.")
            return redirect(url_for("register_squire"))

        try:
            # ✅ Add squire to DB
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO squires (squire_name, real_name, email, team_id, experience_points, level, x_coordinate, y_coordinate, work_sessions)
                VALUES (%s, %s, %s, %s, 0, 1, 0, 0, 0)
            """, (squire_name, real_name, email, team_id))
            conn.commit()
            cursor.close()

            flash("🎉 Welcome to the realm, noble squire!")
            return redirect(url_for("login"))  # Or map page, depending on your flow
        except Exception as e:
            flash("🔥 Something went wrong. Please try again.")
            print("❌ DB Error:", e)
            return redirect(url_for("register_squire"))

    else:
        # Fetch teams to display in dropdown
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT id, team_name FROM teams")
        teams = cursor.fetchall()
        cursor.close()

        return render_template("register.html", teams=teams)

@app.route('/start_quest', methods=['POST'])
def start_quest():
    """Assigns a selected quest to the player."""
    squire_id = session.get("squire_id")

    if not squire_id:
        return jsonify({"success": False, "message": "Session expired. Please log in again."}), 400

    data = request.get_json()
    quest_id = data.get("quest_id")

    if not quest_id:
        return jsonify({"success": False, "message": "Invalid quest selection."}), 400

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # ✅ Update the player's active quest
    cursor.execute("""
        INSERT INTO squire_quest_status (squire_id, quest_id, status)
        VALUES (%s, %s, 'active')
    """, (squire_id, quest_id,))
    conn.commit()

    squire_quest_id = cursor.lastrowid

    cursor.execute("""
        SELECT level from squires where id = %s
    """, (squire_id,))
    l = cursor.fetchone()
    level = l["level"]

    treesize, mountainsize = calculate_feature_counts(level,quest_id)

    generate_terrain_features(conn, squire_id, squire_quest_id,5,10,treesize,3,9,mountainsize)

    # ✅ Store quest ID in session
    session["quest_id"] = quest_id
    session["squire_quest_id"] = squire_quest_id
    message = insert_treasure_chests(conn, quest_id, squire_quest_id)
    message += update_riddle_hints(conn)
    message += f"\n🛡️ You have started Quest {quest_id}!"

    return jsonify({"success": True, "message": message })


@app.route('/quest_select', methods=['GET'])
def quest_select():
    """Displays available quests for the player to choose from."""
    squire_id = session.get("squire_id")

    if not squire_id:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)



    # ✅ Fetch all available courses
    cursor.execute("SELECT id, course_name, description FROM courses")
    courses = cursor.fetchall()  # Returns a list of dictionaries [{id: 1, course_name: "Business Law"}, ...]

    # Look for the course_id in the query parameters first
    course_id = request.args.get("course_id")
    if course_id:
        session['course_id'] = course_id  # Optionally store it in the session for later use
    else:
        # Optionally, use the session value if present
        course_id = session.get("course_id")

    quests = []
    if course_id:
        # Fetch quests related to the selected course
        cursor.execute("""
            SELECT id, quest_name, description FROM quests WHERE
                id not in (
                    select distinct quest_id from squire_quest_status
                    where status = 'completed' and squire_id = %s
                )
                AND status = 'active' AND course_id = %s LIMIT 1
        """, (squire_id, course_id,))
        quests = cursor.fetchall()

    # ✅ Retrieve quest completion message (if any)
    # ✅ Debug session message before rendering
    # Retrieve quest completion message (if any)
    quest_message = session.get("quest_message", [])
    #print("Jinja received:", quest_message)
    logging.debug(f"DEBUG: Quest Message in Session → {quest_message}")

    session.pop("quest_message", None)

    return render_template("quest_select.html", quests=quests, quest_message=quest_message, courses=courses, selected_course_id=course_id)


# 🗺️ Game Map View (Main Game Hub)
@app.route('/map', methods=['GET'])
def map_view():
    squire_id = session.get("squire_id")
    quest_id = session.get("quest_id")
    team_id = session.get('team_id')

    if not squire_id:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

     # ✅ Fetch inventory
    inventory = get_inventory(squire_id, conn)

    try:
        #game_map = display_travel_map(squire_id, quest_id, conn)
        game_map = get_viewport_map(squire_id, quest_id, conn,20)
        xp, gold = get_squire_stats(squire_id, conn)
        hunger = get_hunger_bar(squire_id, conn)

        answered_riddles, total_riddles, progress_percentage = check_quest_progress(squire_id, quest_id, conn)
        progress_bar = display_progress_bar(progress_percentage)

        cursor.execute("SELECT x_coordinate, y_coordinate, level FROM squires WHERE id = %s", (squire_id,))
        position = cursor.fetchone()
        x = position["x_coordinate"]
        y = position["y_coordinate"]
        level = position["level"]

        message = session.pop('message', None)  # Retrieve and clear messages after displaying

        return render_template(
            "map.html",
            quest_id=quest_id,
            game_map=game_map,
            progress_bar=progress_bar,
            xp=xp,
            gold=gold,
            hunger=hunger,
            level=level,
            message=message,
            position=(x,y),
            inventory=inventory,
            team_id=team_id
        )
    except Exception as e:
        logging.error(f"⚠️ Map rendering failed: {str(e)}")
        return jsonify({"error": "Failed to load the map."}), 500


# 🚶 Game Actions (Movement, Shop, Town, Combat)
# mod for AJAX
@app.route('/ajax_move', methods=['POST'])
def ajax_move():
    squire_id = session.get("squire_id")
    quest_id = session.get("quest_id")
    squire_quest_id = session.get("squire_quest_id")

    if not squire_id:
        return jsonify({"error": "Session expired. Please log in again."}), 400

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    direction = request.json.get("direction")  # Get movement direction from AJAX request

    cursor.execute("SELECT x_coordinate, y_coordinate FROM squires WHERE id = %s", (squire_id,))
    position = cursor.fetchone()

    if not position:
        return jsonify({"error": "Player position not found in database."}), 500

    x = position["x_coordinate"]
    y = position["y_coordinate"]

    p = calculate_enemy_encounter_probability(squire_id, quest_id, x,y, conn, squire_quest_id)
    logging.debug(f"Combat Probability: {p}")


    if check_quest_completion(squire_id, quest_id, conn) == True:
        session["quest_completed"] = True  # Store completion state
        if complete_quest(squire_id, quest_id, conn) == True:
            # need to set up for the next so player can choose a new one here
            return jsonify({"redirect": url_for("quest_select")})
    else:
        session.pop("quest_completed", None)  # Ensure it's removed

    event = None
    message = None

    # **Check if movement is valid (including food requirement)**
    if direction in ["N", "S", "E", "W"]:
        result, food_message = consume_food(squire_id, conn)
        if not result:
            # If no food available, return the message immediately (or handle it as needed)
            return jsonify({"message": food_message})
        # Otherwise, include the food message in your response
        else:
            x, y, tm = update_player_position(squire_id, direction, conn)
            message = f"{food_message} \n {tm}"

    elif direction == "V":
        x,y,tm = update_player_position(squire_id, direction, conn)
        visit_town()
        message = "🏰 You arrive in Bitown."
        return jsonify({"redirect": url_for("visit_town")})

    elif direction == "I":
        event = "inventory"
        return jsonify({"redirect": url_for("inventory")})

    # 🔥 Boss Fight Check: if on quest 14 and reached (40,40), trigger the boss fight!
    if quest_id == 14 and x == 40 and y == 40:
        logging.debug("🏰 Boss fight triggered! Player reached (40,40) during quest 14.")
        # Optionally call a function to set up boss fight state:
        #initiate_boss_fight(squire_id, quest_id, conn)  # define this function as needed
        event = "q14bossfight"

        return jsonify({
            "boss_fight": True,
            "message": "You have reached the stronghold! Prepare to face the boss!",
            "event": event
        })

    if x == 0 and y ==0:
        x,y,tm = update_player_position(squire_id, direction, conn)
        visit_town()
        message = "🏰 You arrive in Bitown."
        return jsonify({"redirect": url_for("visit_town")})

    # ✅ Generate Updated Map
    #game_map = display_travel_map(squire_id, quest_id, conn)
    game_map = get_viewport_map(squire_id, quest_id, conn, 20)

    if not game_map:
        logging.error("❌ ERROR: display_travel_map() returned None!")
        return jsonify({"error": "Failed to load the updated map."}), 500


    # **🎁 Treasure Check**
    chest = check_for_treasure_at_location(squire_id, x, y, conn, quest_id, squire_quest_id)
    if chest:
        session["current_treasure"] = chest  # Store chest in session
        event = "treasure"

    # **🏞️ NPC Encounter (5% chance)**
    elif random.random() < 0.02:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT tc.x_coordinate, tc.y_coordinate
            FROM treasure_chests tc
            JOIN riddles r ON tc.riddle_id = r.id
            LEFT JOIN squire_riddle_progress srp
            ON r.id = srp.riddle_id AND srp.squire_id = %s
            WHERE srp.riddle_id IS NULL and r.quest_id = %s and tc.is_opened = 0 AND tc.squire_quest_id = %s
            ORDER BY RAND() LIMIT 1""", (squire_id, quest_id, squire_quest_id))
        coords = cursor.fetchone()

        if coords:
            session['npc_message'] = f"🌿 A wandering trader appears: 'There's a chest at ({coords['x_coordinate']},{coords['y_coordinate']}). I tried to open it but couldn't figure out the riddle. Good luck!'"
            session.modified = True  # Ensure session updates properly
            logging.debug(f"NPC Message Set: {session['npc_message']}")  # Debugging

        event = "npc"

    # **🧙‍♂️ Riddle Encounter (5% chance)**
    elif random.random() < 0.03:

        event = "riddle"

    # **⚔️ Combat Encounter **
    elif random.random() < p:

        event = "enemy"

    # **Build JSON Response**
    response_data = {
        "map": game_map,
        "message": message,
        "position": (x,y),
        "event": event  # Pass event type
    }

    cursor.close()
    return jsonify(response_data)

@app.route('/ajax_status', methods=['GET'])
def ajax_status():
    squire_id = session.get("squire_id")
    quest_id = session.get("quest_id")

    if not squire_id:
        return jsonify({"error": "Not logged in"}), 403

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    cursor.execute("SELECT x_coordinate, y_coordinate FROM squires WHERE id = %s", (squire_id,))
    position = cursor.fetchone()

    if not position:
        return jsonify({"error": "Player position not found in database."}), 500

    x = position["x_coordinate"]
    y = position["y_coordinate"]

    inventory = get_inventory(squire_id, conn)
    hunger = get_hunger_bar(squire_id, conn)
    xp, gold = get_squire_stats(squire_id, conn)

    answered_riddles, total_riddles, progress_percentage = check_quest_progress(squire_id, quest_id, conn)
    progress_bar = display_progress_bar(progress_percentage)

    return jsonify({
        "hunger": hunger,
        "xp": xp,
        "gold": gold,
        "progress_bar": progress_bar,
        "position":[x,y]

    })

@app.route('/inventory', methods=['GET'])
def inventory():
    """Displays the player's inventory on a separate page."""
    squire_id = session.get("squire_id")

    if not squire_id:
        return redirect(url_for("login"))

    conn = get_db_connection()
    inventory = get_inventory(squire_id, conn)  # Fetch inventory items

    return render_template("inventory.html", inventory=inventory)


#Routes for Enemy Combat

@app.template_filter('chance_image')
def chance_image_filter(chance):
    try:
        chance = int(chance)
        if chance >= 70:
            return 'chance_high.png'
        elif chance >= 40:
            return 'chance_medium.png'
        else:
            return 'chance_low.png'
    except:
        return 'chance_unknown.png'


@app.route('/handle_true_false_question', methods=['POST'])
def handle_true_false_question():
    """Allows the player to defeat the enemy by answering a True/False question."""
    squire_id = session.get("squire_id")
    quest_id = session.get("quest_id")
    enemy = session.get("enemy", {})  # Retrieve enemy details from session
    has_weapon = enemy.get("has_weapon", False)  # Get whether the player has the required weapon
    in_forest = session.get("in_forest", False)  # Optional setting, set based on game logic

    if not squire_id or not quest_id or not enemy:
        return jsonify({"success": False, "message": "Session expired. Please log in again."}), 400

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch a random True/False question for this quest
    cursor.execute("""
        SELECT q.id, q.question, q.correct_answer
        FROM true_false_questions q
        LEFT JOIN squire_questions sq ON q.id = sq.question_id AND sq.squire_id = %s
        WHERE q.quest_id = %s AND (sq.times_encountered IS NULL OR sq.times_encountered < 2)
        ORDER BY RAND() LIMIT 1
    """, (squire_id, quest_id))

    question = cursor.fetchone()

    if not question:
        if not has_weapon:
            degrade_gear(squire_id, "zip", conn)
            cursor.execute("UPDATE squires SET experience_points = GREATEST(0, experience_points - 10) WHERE id = %s", (squire_id,))
            conn.commit()
            session['message'] =  "🛑 The enemy forces you to flee because you are unarmed.\n❌ You lose 10 XP and your gear is damaged."
            return jsonify({
                "success": False,
                "message": "🛑 The enemy forces you to flee because you are unarmed.\n❌ You lose 10 XP and your gear is damaged.",
                "flee": True
            })

        return jsonify({
            "success": False,
            "message": "❌ No question available. You must fight!",
            "redirect": url_for("ajax_handle_combat")
        })

    # Get the player's answer from the AJAX request
    user_answer = request.json.get("answer", "").strip().upper()

    if user_answer not in ["T", "F"]:
        return jsonify({"success": False, "message": "Invalid answer. Please submit 'T' or 'F'."}), 400

    is_correct = (user_answer == "T" and question["correct_answer"]) or (user_answer == "F" and not question["correct_answer"])

    if is_correct:
        update_squire_progress(squire_id, conn, enemy["xp_reward"], enemy["gold_reward"])
        session['message'] = f"✅ Correct! The enemy is defeated! You gain {enemy['xp_reward']} XP and {enemy['gold_reward']} bits."
        session['success'] = True

        toast = f"{session['squire_name']} defeated {enemy['name']} and gained {enemy['xp_reward']} XP and {enemy['gold_reward']} bits."
        add_team_message(session['team_id'],toast,conn)

        session.pop("success",None)

        return jsonify({
            "success": True,
            "message": f"✅ Correct! The enemy is defeated! You gain {enemy['xp_reward']} XP and {enemy['gold_reward']} bits.",
            "xp_reward": enemy["xp_reward"],
            "gold_reward": enemy["gold_reward"],
            "defeated": True
        })

    else:
        if has_weapon:


            return jsonify({
                "success": False,
                "message": "❌ Wrong answer! En Garde!",
                "redirect": url_for("ajax_handle_combat")
            })

        # Player loses and is forced to flee
        degrade_gear(squire_id, "zip", conn)
        cursor.execute("UPDATE squires SET experience_points = GREATEST(0, experience_points - 10) WHERE id = %s", (squire_id,))
        conn.commit()

        session['message'] = "🛑 The enemy forces you to flee by your wrong answer.\n❌ You lose 10 XP and your gear is damaged."
        session['success'] = False
        session.pop("success",None)

        return jsonify({
            "success": False,
            "message": "🛑 The enemy forces you to flee by your wrong answer.\n❌ You lose 10 XP and your gear is damaged.",
            "flee": True
        })

@app.route('/answer_question', methods=['GET'])
def answer_question():
    """Displays a True/False question before the player submits an answer."""
    squire_id = session.get("squire_id")
    quest_id = session.get("quest_id")

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch a random question
    cursor.execute("""
        SELECT id, question, correct_answer
FROM true_false_questions
WHERE quest_id = %s
  AND (
    -- If the player has answered all questions correctly, allow all questions:
    ((SELECT COUNT(*) FROM squire_questions
       WHERE squire_id = %s
         AND question_type = 'true_false'
         AND question_id IN (SELECT id FROM true_false_questions WHERE quest_id = %s)
     ) = (SELECT COUNT(*) FROM true_false_questions WHERE quest_id = %s))
    -- Otherwise, only allow questions not already answered correctly:
    OR id NOT IN (SELECT question_id FROM squire_questions WHERE squire_id = %s AND question_type = 'true_false')
  )
ORDER BY RAND()
LIMIT 1;

    """, (quest_id,squire_id,quest_id,quest_id,squire_id))

    question = cursor.fetchone()

    if not question:
        session["battle_summary"] = "No question available. You must fight!"
        return redirect(url_for("ajax_handle_combat"))

    logging.debug(f"Question Text for T/F combat alt {question["question"]}")
    # Store question in session for answer validation
    session["current_question"] = {
        "id": question["id"],
        "text": question["question"]
    }

    return render_template("answer_question.html", question=question)

@app.route('/check_true_false_question', methods=['POST'])
def check_true_false_question():
    """Validates the player's True/False answer."""
    squire_id = session.get("squire_id")
    question_id = request.form.get("question_id")
    user_answer = request.form.get("answer")
    enemy = session.get("enemy", {})  # Retrieve enemy details from session
    session.pop("success",None)

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    enemy = session.get("enemy", {})

    # Get correct answer from DB
    cursor.execute("SELECT correct_answer FROM true_false_questions WHERE id = %s", (question_id,))
    question = cursor.fetchone()

    if not question:
        session["battle_summary"] = "Error: Question not found."
        return redirect(url_for("combat_results"))

    correct_answer = 1 if question["correct_answer"] else 0  # ✅ Ensure DB value is an integer
    user_answer_int = 1 if user_answer == "T" else 0  # ✅ Convert "T" → 1, "F" → 0

    logging.debug(f"Check TF: {squire_id}, {question_id}, {question_id}, {user_answer}, {correct_answer}, {user_answer_int}")
    c= int(correct_answer)
    u= int(user_answer_int)

    if c == u:
        # ✅ Store the correct answer for the player
        cursor.execute("""
            INSERT INTO squire_questions (squire_id, question_id, question_type, answered_correctly)
            VALUES (%s, %s, 'true_false', TRUE)
            ON DUPLICATE KEY UPDATE answered_correctly = TRUE
        """, (squire_id, question_id))
        conn.commit()



        # Check if this was for a job
        pending_job = session.pop("pending_job", None)
        if pending_job:
            level = cursor.execute("SELECT level FROM squires WHERE id = %s", (squire_id,))
            level = cursor.fetchone()['level']
            payout = random.randint(pending_job["min_payout"], pending_job["max_payout"]) * level

            # Pay player
            cursor.execute("""
                UPDATE teams
                SET gold = gold + %s
                WHERE id = (SELECT team_id FROM squires WHERE id = %s)
            """, (payout, squire_id))

            # Increment work_sessions
            cursor.execute("""
                UPDATE squires
                SET work_sessions = work_sessions + 1
                WHERE id = %s
            """, (squire_id,))

            conn.commit()
            session["job_message"] = f"✅ You completed '{pending_job['job_name']}' and earned 💰 {payout} bits!"
            toast = f"{session['squire_name']} completed '{pending_job['job_name']}' and earned 💰 {payout} bits."
            add_team_message(session['team_id'],toast,conn)

            return redirect(url_for("visit_town"))

        xp_reward = enemy.get("xp_reward", 0)
        gold_reward = enemy.get("gold_reward", 0)
        update_squire_progress(squire_id, conn, xp_reward, gold_reward)

        toast = f"{session['squire_name']} defeated {enemy['name']} and gained {enemy['xp_reward']} XP and {enemy['gold_reward']} bits."
        add_team_message(session['team_id'],toast,conn)

        session["combat_result"] = f"✅ Correct! You have defeated the enemy and earned {xp_reward} XP and {gold_reward} bits."
        session["success"] = True
    else:
        # Fail scenario for job or enemy
        if session.get("pending_job"):
            session.pop("pending_job", None)
            session["job_message"] = "❌ Incorrect! You failed the task and earned nothing."
            return redirect(url_for("visit_town"))

        degrade_gear(squire_id, enemy["weakness"], conn)
        cursor.execute("UPDATE squires SET experience_points = GREATEST(0, experience_points - %s) WHERE id = %s", (enemy["xp_reward"],squire_id,))
        conn.commit()

        session["combat_result"] = f"❌ Incorrect! You are defeated by {enemy['name']} and lose some experience points!"
        session["success"] = False


    return render_template(
        "combat_results.html",
        success=session.pop("success", None),
        combat_result=session.pop("combat_result", "")
    )


# ⚔️ Combat
@app.route('/combat', methods=['GET', 'POST'])
def combat():
    """Displays combat screen where player chooses to fight or flee."""
    enemy = session.get('enemy')
    squire_id = session.get("squire_id")
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    if not enemy:
        logging.debug("No enemy found in session, redirecting to map.")
        return redirect(url_for('map_view'))  # No enemy data? Go back to map.

    # Fetch player's level and max hunger as before
    cursor.execute("SELECT level, x_coordinate, y_coordinate FROM squires WHERE id = %s", (squire_id,))
    squire = cursor.fetchone()
    level = squire["level"]
    x, y = squire["x_coordinate"], squire["y_coordinate"]


    #return necessary initial values for combat
    update_work_for_combat(squire_id,conn)
    max_hunger, food = get_player_max_hunger(squire_id, conn)
    base_hit_chance = calculate_hit_chance(squire_id, level, conn)
    hit_chance = int(min(base_hit_chance + combat_mods(squire_id, enemy["name"], level, conn), 95))
    player_max_hunger = min(max_hunger + hunger_mods(squire_id, conn), 8)


    mod_for_distance = abs(x * y)
    enemy_max_hunger_base = enemy["max_hunger"]
    enemy_in_forest = enemy.get("in_forest")
    enemy_in_mountain = enemy.get("in_mountain")
    logging.debug(f"Dist / Base / F / M: {mod_for_distance} {enemy_max_hunger_base} {enemy_in_forest}  {enemy_in_mountain}")
    mod_enemy_max_hunger = mod_enemy_hunger(mod_for_distance, enemy_max_hunger_base, enemy_in_forest, enemy_in_mountain)
    logging.debug(f"mod_enemy_max_hunger = {mod_enemy_max_hunger}")
    safe_chances = calc_flee_safely(mod_enemy_max_hunger, player_max_hunger, hit_chance)

    # initialize session variables for battle
    player_current_hunger = 0
    enemy_current_hunger = 0
    battle_log = session.get("battle_log", [])

    # Save updated values in session
    session["player_current_hunger"] = player_current_hunger
    session["enemy_current_hunger"] = enemy_current_hunger
    session["player_max_hunger"] = player_max_hunger
    session["mod_enemy_max_hunger"] = mod_enemy_max_hunger
    session["hit_chance"] = hit_chance
    session["mod_for_distance"] = mod_for_distance
    session["safe_chances"] = safe_chances

    return render_template('combat.html', enemy=enemy)

@app.route('/encounter_enemy', methods=['Get'])
def encounter_enemy():
    """Handles an enemy encounter with a choice between knowledge and combat."""
    squire_id = session.get("squire_id")
    quest_id = session.get("quest_id")

    if not squire_id:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch player's position
    cursor.execute("SELECT x_coordinate, y_coordinate, level FROM squires WHERE id = %s", (squire_id,))
    position = cursor.fetchone()
    x, y = position["x_coordinate"], position["y_coordinate"]
    level = position["level"]

    # Check if the player is in a forest
    cursor.execute("SELECT COUNT(*) as in_forest FROM map_features WHERE x_coordinate = %s AND y_coordinate = %s AND terrain_type = 'forest'", (x, y))
    in_forest = cursor.fetchone()["in_forest"]

    cursor.execute("SELECT COUNT(*) as in_mountain FROM map_features WHERE x_coordinate = %s AND y_coordinate = %s AND terrain_type = 'mountain'", (x, y))
    in_mountain = cursor.fetchone()["in_mountain"]

    # Fetch a random enemy
    cursor.execute("SELECT id, enemy_name, description, weakness, gold_reward, xp_reward, hunger_level, max_hunger,static_image FROM enemies where is_boss = 0 and min_level <= %s ORDER BY RAND() LIMIT 1", (level,))
    enemy = cursor.fetchone()

    if enemy:
        fight_with = enemy["weakness"]

        cursor.execute("SELECT count(*) as has_weapon FROM inventory WHERE squire_id = %s AND item_name = %s", (squire_id, fight_with))
        weapon = cursor.fetchone()["has_weapon"]

        if weapon > 0:
            has_weapon = True

        # ✅ Ensure `session['enemy']` is JSON-serializable
        session['enemy'] = {
            "max_hunger": int(enemy["max_hunger"]),
            "id": int(enemy["id"]),  # Ensure it's an integer
            "name": str(enemy["enemy_name"]),
            "description": str(enemy["description"]),
            "weakness": str(enemy["weakness"]),
            "gold_reward": int(enemy["gold_reward"]),
            "xp_reward": int(enemy["xp_reward"]),
            "in_forest": bool(in_forest),  # Convert to True/False
            "in_mountain": bool(in_mountain),
            "has_weapon": bool(weapon),
            "static_image": str(enemy["static_image"])
        }


        event = "enemy"
        logging.debug(f"Storing in session: {session.get('enemy')}")


    return redirect(url_for('combat'))

@app.route('/encounter_boss', methods=['Get'])
def encounter_boss():
    squire_id = session.get("squire_id")
    quest_id = session.get("quest_id")

    if not squire_id:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch player's position
    cursor.execute("SELECT x_coordinate, y_coordinate, level FROM squires WHERE id = %s", (squire_id,))
    position = cursor.fetchone()
    x, y = position["x_coordinate"], position["y_coordinate"]
    level = position["level"]

    # Fetch a random enemy
    cursor.execute("SELECT id, enemy_name, description, weakness, gold_reward, xp_reward, hunger_level, max_hunger FROM enemies where enemy_name like %s",('%%Lexiconis%%',))
    boss = cursor.fetchone()

    logging.debug(f"Encounter_boss {x}, {y}: {level}")

    if boss:
        # ✅ Ensure `session['enemy']` is JSON-serializable
        session['boss'] = {
            "max_hunger": int(boss["max_hunger"]),
            "id": int(boss["id"]),  # Ensure it's an integer
            "name": str(boss["enemy_name"]),
            "description": str(boss["description"]),
            "weakness": str(boss["weakness"]),
            "gold_reward": int(boss["gold_reward"]),
            "xp_reward": int(boss["xp_reward"])
        }


        event = "boss"
        logging.debug(f"Storing in session: {session.get('boss')}")


    return redirect(url_for('boss_combat'))

@app.route('/boss_combat', methods=['GET', 'POST'])
def boss_combat():
    """Displays combat screen where player chooses to fight or flee."""
    boss = session.get('boss')
    squire_id = session.get("squire_id")
    quest_id = session.get("quest_id")

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    logging.debug("in /boss_combat route.")

    if not boss:
        logging.debug("Guess the boss is out to lunch: redirecting to map.")
        return redirect(url_for('map_view'))  # No enemy data? Go back to map.


    # Fetch player's position
    cursor.execute("SELECT x_coordinate, y_coordinate, level FROM squires WHERE id = %s", (squire_id,))
    position = cursor.fetchone()
    x, y = position["x_coordinate"], position["y_coordinate"]
    level = position["level"]

    max_hunger, food = get_player_max_hunger(squire_id, conn)
    player_max_hunger = min(max_hunger + hunger_mods(squire_id, conn), 8)
    boss_max_hunger = boss["max_hunger"]


    # initialize session variables for battle
    if session.get("player_current_hunger") is None:
        session["player_current_hunger"] = 0
    if session.get("boss_current_hunger") is None:
        session["boss_current_hunger"] = 0
#    if session["battle_log"] is None:
#        battle_log = session.get("battle_log", [])

    # Save updated values in session
    #session["player_current_hunger"] = player_current_hunger
    #session["boss_current_hunger"] = boss_current_hunger
    session["player_max_hunger"] = int(player_max_hunger)
    session["boss_max_hunger"] = int(boss_max_hunger)

    return render_template('boss_combat.html', boss=boss)

@app.route('/ajax_handle_boss_combat', methods=['POST', 'GET'])
def ajax_handle_boss_combat():
    """Handles combat via AJAX by updating hunger levels and returning JSON."""
    boss = session.get("boss")
    squire_id = session.get("squire_id")

    if not boss or not squire_id:
        logging.error("Missing boss or squire_id in session")
        return jsonify({"redirect": url_for("map_view")})

    try:
        player_current_hunger = session.get("player_current_hunger", 0)
        boss_current_hunger = session.get("boss_current_hunger", 0)
        player_max_hunger = session.get("player_max_hunger", 0)
        boss_max_hunger = session.get("boss_max_hunger", 0)

        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        logging.debug(f"Boss Status: {boss_current_hunger} / {boss_max_hunger} Player Status {player_current_hunger} / {player_max_hunger}")

        # route based on the button pushed by the user
        action = request.form.get("action")

        if action == "flee":
            if flee_safely(boss_max_hunger, player_max_hunger, 0) == False:
                session["combat_result"] = "🏃 You managed to escape safely!"
            else:
                degrade_gear(squire_id, boss["weakness"], conn)
                session["combat_result"] = "🏃 You managed to escape but your armor was damaged during the retreat."
            # Clear session combat variables
            cleanup_session()
            cursor.close()
            return jsonify({"redirect": url_for("combat_results")})

        else: #answer questions
            return jsonify({"redirect": url_for("answer_MC_question")})

    except Exception as e:
        logging.error(f"Error in boss combat: {str(e)}")
        return jsonify({"error": "An error occurred during combat"}), 500


#present questions
@app.route('/answer_MC_question', methods=['GET'])
def answer_MC_question():
    boss = session.get('boss')
    squire_id = session.get("squire_id")
    quest_id = session.get("quest_id")

    player_current_hunger = session["player_current_hunger"]
    boss_current_hunger = session["boss_current_hunger"]

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch a random question -- edit this to be the multiple choice pool from unit 1
    cursor.execute("""
        SELECT id, question_text, optionA, optionB, optionC, optionD, correctanswer
FROM multiple_choice_questions
WHERE quest_id < %s and id not in (select question_id from squire_questions where question_type = 'multiple_choice' and squire_id = %s)
ORDER BY RAND()
LIMIT 1;

    """, (quest_id,squire_id,))

    question = cursor.fetchone()

    if not question:
        session["battle_summary"] = "No question available. You must flee!"
        return redirect(url_for("ajax_handle_boss_combat"))

    logging.debug(f"Question Text for M/C combat alt {question["question_text"]}")
    # Store question in session for answer validation
    session["current_question"] = {
        "id": question["id"],
        "text": question["question_text"],
        "optionA": question["optionA"],
        "optionB": question["optionB"],
        "optionC": question["optionC"],
        "optionD": question["optionD"],
        "correctanswer": question["correctanswer"]
    }

    return render_template('boss_combat.html', boss=boss)


#then need a route to check if the question was answered correctly so that that can be recorded as either
#increasing the player's hunger or the enemy's hunger
@app.route('/check_MC_question', methods=['POST'])
def check_MC_question():
    boss = session.get('boss')
    player_current_hunger = session["player_current_hunger"]
    boss_current_hunger = session["boss_current_hunger"]

    """Validates the player's MC answer."""
    squire_id = session.get("squire_id")
    question_id = request.form.get("question_id")
    user_answer = request.form.get("selected_option")
    enemy_message = None
    player_message = None

    logging.debug(f"Check_MC_question qid / user_answer {question_id} / {user_answer}")
    logging.debug(f"Check_MC_question pch / pmh {player_current_hunger} / {session['player_max_hunger']}")


    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    enemy = session.get("enemy", {})

    # Get correct answer from DB
    cursor.execute("SELECT correctanswer FROM multiple_choice_questions WHERE id = %s", (question_id,))
    question = cursor.fetchone()

    if not question:
        session["battle_summary"] = "Error: Question not found."
        return redirect(url_for("combat_results"))

    if user_answer == question["correctanswer"]:

        cursor.execute("""
            INSERT INTO squire_questions (squire_id, question_id, question_type, answered_correctly)
            VALUES (%s, %s, 'multiple_choice', TRUE)
            ON DUPLICATE KEY UPDATE answered_correctly = TRUE
        """, (squire_id, question_id))
        conn.commit()



        session["boss_current_hunger"] = boss_current_hunger + 1
        session["question_id"] = None
        enemy_message = f"💥 Good Answer! {boss['name']} is getting hungrier."
    else:
        logging.debug("Boss Hit Player")
        player_message = f"❌ Not good, Squire! You are getting hungrier."

        session["player_current_hunger"] = player_current_hunger + 1
        session["question_id"] = None

    session.pop("current_question", None)

    # Now check win/lose conditions immediately.
    if boss_current_hunger >= int(session["boss_max_hunger"]):
        # Player wins: boss is too hungry!
        session["boss_defeated"] = True
        xp = boss["xp_reward"]
        bitcoin = boss["gold_reward"]
        update_squire_progress(squire_id, conn, xp, bitcoin)
        session["combat_result"] = f"🍕 The {boss['name']} is too hungry to continue! They run off to eat a pizza.\nYou gain {xp} XP and {bitcoin} bits."
        # Clear combat variables
        session.pop("boss", None)
        session.pop("player_current_hunger", None)
        session.pop("boss_current_hunger", None)

        toast = f"{session['squire_name']} defeated {boss['name']} and gained {boss['xp_reward']} XP and {boss['gold_reward']} bits."
        add_team_message(session['team_id'],toast,conn)

        return redirect(url_for("combat_results"))

    if player_current_hunger >= int(session["player_max_hunger"]):
        # Player loses: too hungry!
        degrade_gear(squire_id, boss.get("weakness"), conn)
        cursor.execute("UPDATE squires SET experience_points = GREATEST(0, experience_points - 100) WHERE id = %s", (squire_id,))
        conn.commit()
        session["combat_result"] = "🛑 You are too hungry to continue fighting! The enemy forces you to flee.\n❌ You lose 100 XP."
        # Clear combat variables
        session.pop("boss", None)
        session.pop("player_current_hunger", None)
        session.pop("boss_current_hunger", None)
        return redirect(url_for("combat_results"))

    if enemy_message:
        session["enemy_message"] = enemy_message
    else:
        session["player_message"] = player_message

    return redirect(url_for("boss_combat"))

@app.route('/ajax_handle_combat', methods=['POST'])
def ajax_handle_combat():
    """Handles combat via AJAX by updating hunger levels and returning JSON."""
    enemy = session.get("enemy")
    squire_id = session.get("squire_id")
    player_current_hunger = session["player_current_hunger"]
    enemy_current_hunger = session["enemy_current_hunger"]
    player_max_hunger = session["player_max_hunger"]
    mod_enemy_max_hunger = session["mod_enemy_max_hunger"]
    hit_chance = session["hit_chance"]
    mod_for_distance = session["mod_for_distance"]
    session.pop("success",None)


    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    if not enemy:
        return jsonify({"redirect": url_for("map_view")})

    # Initialize combat if not already active
    if "combat_active" not in session or not session["combat_active"]:
        session["player_current_hunger"] = 0
        session["enemy_current_hunger"] = 0
        session["battle_log"] = []
        session["combat_active"] = True

    # route based on the button pushed by the user
    action = request.form.get("action")

    if action == "flee":

        if flee_safely(mod_enemy_max_hunger,player_max_hunger, hit_chance) == False:
            session["combat_result"] = "🏃 You managed to escape safely!"
            session["success"] = True
        else:
            degrade_gear(squire_id, enemy["weakness"], conn)
            session["combat_result"] = "🏃 You managed to escape but your armor was damaged during the retreat."
            session["success"] = False
        # Clear session combat variables
        session.pop("enemy", None)
        session.pop("player_current_hunger", None)
        session.pop("enemy_current_hunger", None)
        session.pop("combat_active", None)
        session.pop("battle_log", None)
        session.pop("success",None)
        cursor.close()
        return jsonify({"redirect": url_for("combat_results")})
    elif action == "question":
        #re-route player to answer a question
        # Clear session combat variables
        session.pop("enemy", None)
        session.pop("player_current_hunger", None)
        session.pop("enemy_current_hunger", None)
        session.pop("combat_active", None)
        session.pop("battle_log", None)
        cursor.close()
        return jsonify({"redirect": url_for("answer_question")})

    else:
        battle_log = []

        # Player attack attempt
        if random.randint(1, 100) <= hit_chance:
            enemy_current_hunger += 1
            battle_log.append(f"💥 You hit the {enemy['name']} with your {enemy['weakness']}! They are getting hungrier.")
        else:
            player_current_hunger += 1
            battle_log.append(f"❌ Ouch! Bad Touch, {enemy['name']}! You are getting hungrier.")

    # Check for combat end conditions
        # result if player lost
        if player_current_hunger >= player_max_hunger:
            degrade_gear(squire_id, enemy["weakness"], conn)
            cursor.execute("UPDATE squires SET experience_points = GREATEST(0, experience_points - %s) WHERE id = %s", (enemy["xp_reward"],squire_id,))
            conn.commit()
            outcome = f"🛑 You are too hungry to continue fighting! The enemy forces you to flee and damages your gear.\n❌ You lose some XP."
            session["combat_result"] = outcome
            session["success"] = False

            # Clear session variables
            session.pop("enemy", None)
            session.pop("player_current_hunger", None)
            session.pop("enemy_current_hunger", None)
            session.pop("combat_active", None)
            session.pop("battle_log", None)

            cursor.close()
            return jsonify({"redirect": url_for("combat_results")})

        # result if player won
        if enemy_current_hunger >= mod_enemy_max_hunger:
            xp = enemy["xp_reward"]
            bitcoin = enemy["gold_reward"]
            # Apply additional modifiers based on location
            if enemy.get("in_forest"):
                xp += 10
            if 51 <= mod_for_distance <= 150:
                xp += 5 if not enemy.get("in_forest") else 15
                bitcoin += 10
            elif 151 <= mod_for_distance <= 500:
                xp += 10 if not enemy.get("in_forest") else 30
                bitcoin += 20
            elif 501 <= mod_for_distance <= 1000:
                xp += 20 if not enemy.get("in_forest") else 40
                bitcoin += 25
            elif mod_for_distance > 1000:
                xp += 25 if not enemy.get("in_forest") else 55
                bitcoin += 100

            update_squire_progress(squire_id, conn, xp, bitcoin)
            degrade_gear(squire_id, enemy["weakness"], conn)
            outcome = f"🍕 The {enemy['name']} is too hungry to continue! They run off to eat a pizza.\nYou gain {xp} XP and {bitcoin} bits."
            session["combat_result"] = outcome

            # ✅ Reset combat flag and work sessions after combat
            session["forced_combat"] = False
            session["success"] = True
            cursor.execute("UPDATE squires SET work_sessions = 0 WHERE id = %s", (squire_id,))
            conn.commit()

            toast = f"{session['squire_name']} defeated {enemy['name']} and gained {xp} XP and {bitcoin} bits."
            add_team_message(session['team_id'],toast,conn)

            # Clear combat session variables
            session.pop("enemy", None)
            session.pop("player_current_hunger", None)
            session.pop("enemy_current_hunger", None)
            session.pop("combat_active", None)
            session.pop("battle_log", None)

            cursor.close()

            return jsonify({"redirect": url_for("combat_results")})


    # Save updated values in session
    session["player_current_hunger"] = player_current_hunger
    session["enemy_current_hunger"] = enemy_current_hunger
    session["battle_log"] = battle_log

    cursor.close()
    # Return updated combat data as JSON
    return jsonify({
        "player_current_hunger": player_current_hunger,
        "enemy_current_hunger": enemy_current_hunger,
        "battle_log": battle_log,
        "hit_chance": hit_chance,
        "player_max_hunger": player_max_hunger,
        "mod_enemy_max_hunger": mod_enemy_max_hunger
    })


@app.route('/combat_results', methods=['GET'])
def combat_results():
    return render_template(
        "combat_results.html",
        success=session.pop("success", None),
        combat_result=session.pop("combat_result", "")
    )
#Town Routes here

@app.route('/town', methods=['GET'])
def visit_town():
    """Displays the town menu with options to shop, work, or leave."""
    squire_id = session.get("squire_id")
    job_message = session.get("job_message")
    if not squire_id:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch town-related stats
    cursor.execute("SELECT level FROM squires WHERE id = %s", (squire_id,))
    squire_data = cursor.fetchone()
    level = squire_data["level"]

    return render_template("town.html", level=level, job_message=job_message)

# 🏪 Shop
@app.route('/shop', methods=['GET'])
def shop():
    """Displays the shop where players can buy items."""
    squire_id = session.get("squire_id")
    if not squire_id:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT level from squires where id = %s",(squire_id,))
    level = cursor.fetchone()['level']

    # Fetch available shop items
    cursor.execute("SELECT id, item_name, price, uses FROM shop_items where min_level <= %s",(level,))
    items = cursor.fetchall()

    # Fetch player's current balance
    cursor.execute("select gold from teams where id in (select team_id from squires where id = %s);", (squire_id,))
    player_gold = cursor.fetchone()["gold"]

    session["player_gold"] = player_gold

    return render_template("shop.html", items=items, player_gold=player_gold)

@app.route('/buy_item', methods=['POST'])
def buy_item():
    try:
        data = request.get_json()  # Explicitly parse JSON data
        item_id = data.get("item_id")

        if not item_id:
            return jsonify({"success": False, "message": "Invalid item ID received"}), 400

        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # Fetch the item details
        cursor.execute("SELECT id, item_name, description, price, item_type, uses FROM shop_items WHERE id = %s", (item_id,))
        item = cursor.fetchone()

        if not item:
            return jsonify({"success": False, "message": "Item not found"}), 404

        # Fetch player's gold balance
        squire_id = session.get("squire_id")
        cursor.execute("SELECT gold FROM teams WHERE id IN (SELECT team_id FROM squires WHERE id = %s)", (squire_id,))
        player = cursor.fetchone()

        if not player:
            return jsonify({"success": False, "message": "Player not found"}), 404

        player_gold = player["gold"]

        if player_gold < item["price"]:
            return jsonify({"success": False, "message": "Not enough gold to buy this item!"})

        # Deduct gold and add the item to inventory
        cursor.execute("UPDATE teams SET gold = gold - %s WHERE id IN (SELECT team_id FROM squires WHERE id = %s)", (item["price"], squire_id))
        cursor.execute("INSERT INTO inventory (squire_id, item_name, uses_remaining, item_type, description) VALUES (%s, %s, %s, %s, %s)",
                       (squire_id, item["item_name"], item["uses"], item["item_type"], item["description"]))

        conn.commit()
        cursor.close()

        # Return updated gold balance
        return jsonify({
            "success": True,
            "message": f"You bought {item['item_name']}!",
            "new_gold": player_gold - item["price"]
        })

    except Exception as e:
        #print(f"Error: {str(e)}")  # Log error in console
        return jsonify({"success": False, "message": "Something went wrong!"}), 500

@app.route('/town_work', methods=['GET', 'POST'])
def town_work():
    """Allows players to take on jobs to earn gold."""
    squire_id = session.get("squire_id")
    if not squire_id:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT level from squires where id = %s",(squire_id,))
    level = cursor.fetchone()['level']

    # ✅ Check if combat is required
    if session.get("forced_combat"):
        session["job_message"] = "You must face the dangers beyond town before working again!"
        return redirect(url_for("visit_town"))


    # ✅ Get current work sessions for the player
    cursor.execute("SELECT work_sessions FROM squires WHERE id = %s", (squire_id,))
    result = cursor.fetchone()
    work_sessions = result["work_sessions"] if result else 0

    max_work_sessions = 3  # ✅ Limit on how many times a player can work before facing a monster

    if work_sessions >= max_work_sessions:
        session["forced_combat"] = True  # ✅ Store in session that combat is required
        session["job_message"] = "You must face the dangers beyond town before working again!"
        return redirect(url_for("visit_town"))

    if request.method == 'POST':
        job_id = request.form.get("job_id")

        # Fetch job details
        cursor.execute("SELECT job_name, min_payout, max_payout FROM jobs WHERE id = %s", (job_id,))
        job = cursor.fetchone()

        if not job:
            session["message"] = "❌ Invalid job selection!"
            return redirect(url_for("town_work"))

        # Generate payout within the range
        payout = random.randint(job["min_payout"], job["max_payout"]) * level

        # ✅ Save job info to session before answering question
        session["pending_job"] = {
            "job_id": job_id,
            "job_name": job["job_name"],
            "min_payout": job["min_payout"],
            "max_payout": job["max_payout"]
        }

        return redirect(url_for("answer_question"))

    # Fetch available jobs
    cursor.execute("SELECT id, job_name, description, min_payout, max_payout FROM jobs")
    jobs = cursor.fetchall()

    return render_template("town_work.html", jobs=jobs)

@app.route('/hall_of_fame', methods=['GET'])
def hall_of_fame():
    """Displays the Hall of Fame leaderboard."""
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch top 5 players by XP
    cursor.execute("SELECT squire_name, experience_points FROM squires ORDER BY experience_points DESC LIMIT 10")
    leaders = cursor.fetchall()

    return render_template("hall_of_fame.html", leaders=leaders)


## riddles and treasure encounters here

@app.route('/riddle_encounter', methods=['GET'])
def riddle_encounter():
    """Fetches a random riddle and displays it in the HTML page."""
    squire_id = session.get("squire_id")
    quest_id = session.get("quest_id")

    if not squire_id:
        return redirect(url_for("login"))

    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # Fetch a random unanswered riddle
        cursor.execute("""
            SELECT r.id, r.riddle_text, r.answer, r.hint, r.word_length_hint, r.word_count
            FROM riddles r
            LEFT JOIN squire_riddle_progress srp
            ON r.id = srp.riddle_id AND srp.squire_id = %s
            WHERE srp.riddle_id IS NULL AND r.quest_id = %s
            ORDER BY RAND() LIMIT 1""",
            (squire_id, quest_id))

        riddle = cursor.fetchone()

        if not riddle:
            session["riddle_message"] = "You've solved all riddles for this quest!"
            return redirect(url_for("map_view"))  # No more riddles, return to map

        #determine what hints the player will receive based on the items that they have in their inventory
        show_hint = ishint(squire_id, conn)
        show_word_length = iswordlengthhint(squire_id, conn)
        show_word_count = iswordcounthint(squire_id, conn)

        # Store riddle in session to verify answer later
        session["current_riddle"] = {
            "id": riddle["id"],
            "text": riddle["riddle_text"],
            "answer": riddle["answer"],
            "hint": riddle["hint"],
            "word_length_hint": riddle["word_length_hint"],
            "word_count": riddle["word_count"],
            "show_hint": show_hint,
            "show_word_length": show_word_length,
            "show_word_count": show_word_count
        }

        return render_template("riddle.html", riddle=riddle, show_hint=show_hint, show_word_count=show_word_count, show_word_length=show_word_length)
    except Exception as e:
        logging.error(f"Error in riddle_encounter: {str(e)}")
        return redirect(url_for("map_view"))
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

@app.route('/check_riddle', methods=['POST'])
def check_riddle():
    """Checks if the answer to the riddle is correct."""
    squire_id = session.get("squire_id")
    quest_id = session.get("quest_id")

    logging.debug(f"Session contents: {session}")
    logging.debug(f"Current riddle in session: {session.get('current_riddle')}")

    if not squire_id or "current_riddle" not in session:
        logging.error(f"No active riddle found. Squire ID: {squire_id}, Session: {session}")
        return jsonify({"success": False, "message": "❌ No active riddle found!"})

    try:
        user_answer = request.form.get("answer", "").strip().lower()
        correct_answer = session["current_riddle"]["answer"].strip().lower()

        logging.debug(f"User answer: {user_answer}, Correct answer: {correct_answer}")

        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        if user_answer == correct_answer:
            riddle_id = session["current_riddle"]["id"]

            # Mark riddle as solved
            cursor.execute(
                "INSERT INTO squire_riddle_progress (squire_id, riddle_id, quest_id) VALUES (%s, %s, %s)",
                (squire_id, riddle_id, quest_id))
            conn.commit()

            cursor.execute("""
                INSERT INTO squire_questions (squire_id, question_id, question_type, answered_correctly)
                VALUES (%s, %s, 'riddle', TRUE)
                ON DUPLICATE KEY UPDATE answered_correctly = TRUE
            """, (squire_id, riddle_id))
            conn.commit()

            special_item = calculate_riddle_reward(conn, riddle_id, squire_id)

            toast = f"{session['squire_name']} solved a riddle and received {special_item}."
            add_team_message(session['team_id'],toast,conn)

            session.pop("current_riddle", None)  # Remove riddle from session
            return jsonify({"success": True, "message": f"🎉 Correct! The wizard nods in approval and grants you {special_item}"})
        else:
            return jsonify({"success": False, "message": "❌ Incorrect! Try again."})
    except Exception as e:
        logging.error(f"Error in check_riddle: {str(e)}")
        return jsonify({"success": False, "message": "❌ An error occurred while checking your answer."})
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

@app.route('/treasure_encounter', methods=['GET'])
def treasure_encounter():
    """Handles the treasure chest encounter and displays the riddle."""
    squire_id = session.get("squire_id")
    quest_id = session.get("quest_id")

    if "current_treasure" not in session:
        session["treasure_message"] = "No treasure found at this location."
        return redirect(url_for("map_view"))

    chest = session["current_treasure"]  # Retrieve stored treasure chest

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch the unopened treasure chest using session data
    cursor.execute("""
        SELECT id, riddle_id, gold_reward, xp_reward, food_reward, special_item
        FROM treasure_chests
        WHERE id = %s AND is_opened = FALSE
    """, (chest["id"],))
    chest_data = cursor.fetchone()

    if not chest_data:
        session["treasure_message"] = "No unopened treasure chests remain."
        return redirect(url_for("map_view"))

    # Fetch the riddle linked to this chest
    cursor.execute("""
        SELECT riddle_text, answer, hint, word_length_hint, word_count, quest_id, difficulty
        FROM riddles WHERE id = %s
    """, (chest["riddle_id"],))
    riddle = cursor.fetchone()

    show_hint = ishint(squire_id,conn)
    if show_hint == True:
        return_hint = riddle["hint"]
    else:
        return_hint = None

    if not riddle:
        session["treasure_message"] = "No riddle found for this chest."
        return redirect(url_for("map_view"))

    # Update the session with full treasure details
    session["current_treasure"] = {
        "id": chest_data["id"],
        "riddle_id": chest_data["riddle_id"],
        "gold_reward": chest_data["gold_reward"],
        "xp_reward": chest_data["xp_reward"],
        "food_reward": chest_data["food_reward"],
        "special_item": chest_data["special_item"],
        "riddle_text": riddle["riddle_text"],
        "answer": riddle["answer"],
        "hint": return_hint,
        "difficulty": riddle["difficulty"]
    }

    return render_template("treasure.html", chest=session["current_treasure"], response={})


@app.route('/check_treasure', methods=['POST'])
def check_treasure():
    """Checks if the answer to the treasure riddle is correct."""
    squire_id = session.get("squire_id")
    quest_id = session.get("quest_id")

    if not squire_id or "current_treasure" not in session:
        return jsonify({"success": False, "message": "❌ No active chest found!"})

    user_answer = request.form.get("answer").strip().lower()
    chest = session["current_treasure"]

    correct_answer = chest["answer"].strip().lower()

    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    if user_answer == correct_answer:
        # Reward the player

        cursor.execute("""
            INSERT INTO squire_questions (squire_id, question_id, question_type, answered_correctly)
            VALUES (%s, %s, 'riddle', TRUE)
            ON DUPLICATE KEY UPDATE answered_correctly = TRUE
        """, (squire_id, chest["riddle_id"]))
        conn.commit()

        gold = chest["gold_reward"]
        xp = chest["xp_reward"]
        food = chest["food_reward"]
        special_item = chest["special_item"]
        reward_messages = []
        toast_messages = []

        if gold > 0:
            reward_messages.append(f"💰 You found {gold} bitcoin!")
            toast_messages.append(f"{gold} bitcoin")
            cursor.execute("UPDATE teams SET gold = gold + %s WHERE id = (SELECT team_id FROM squires WHERE id = %s)", (gold, squire_id))

        if xp > 0:
            reward_messages.append(f"🎖️ You gained {xp} XP!")
            toast_messages.append(f" / {xp} XP")
            cursor.execute("UPDATE squires SET experience_points = experience_points + %s WHERE id = %s", (xp, squire_id))

        if food > 0:
            reward_messages.append(f"🍖 You found {food} special food items!")
            toast_messages.append(f" / magic food")
            cursor.execute("INSERT INTO inventory (squire_id, item_name, description, uses_remaining, item_type) VALUES (%s, 'Magic Pizza', 'Restores hunger', 15, 'food')", (squire_id,))

        if special_item:
            # Adjust item uses based on difficulty
            uses_remain = {"Easy": 10, "Medium": 25, "Hard": 50}.get(chest["difficulty"], 10)
            reward_messages.append(f"🛡️ You discovered a rare item: {special_item}!")
            toast_messages.append(f" / {special_item}")


            cursor.execute("INSERT INTO inventory (squire_id, item_name, description, uses_remaining, item_type) VALUES (%s, %s, 'A special item that affects gameplay', %s, 'gear')",
                           (squire_id, special_item, uses_remain))

        # Mark the chest as opened
        cursor.execute("UPDATE treasure_chests SET is_opened = TRUE WHERE id = %s", (chest["id"],))
        cursor.execute("INSERT INTO squire_riddle_progress (squire_id, riddle_id, quest_id, answered_correctly) VALUES (%s, %s, %s, 1)",
                       (squire_id, chest["riddle_id"], quest_id,))
        toast_str = ", ".join(toast_messages)

        toast = f"{session['squire_name']} solved a riddle and received {toast_str}."
        add_team_message(session['team_id'],toast,conn)

        conn.commit()
        cursor.close()

        session.pop("current_treasure", None)  # Remove from session
        return jsonify({"success": True, "message": "✅ Correct! The chest unlocks! " + " ".join(reward_messages)})

    else:
        return jsonify({"success": False, "message": "❌ Incorrect! The chest remains locked. Try again later."})
