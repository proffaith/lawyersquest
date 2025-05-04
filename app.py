from flask import Flask, render_template, request, redirect, url_for, session as flask_session, jsonify, flash
import pymysql
import random
import logging
import socks
import socket
from urllib.parse import urlparse
from sqlalchemy import create_engine, func, and_
from sqlalchemy.pool import QueuePool
import os
import re
import requests
from dotenv import load_dotenv
from datetime import datetime
from collections import defaultdict
import uuid
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail


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
from init import generate_terrain_features_dynamic
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

from db import Squire, Course, Team, engine, db_session, Team, TravelHistory, Quest, SquireQuestion, SquireRiddleProgress, Riddle, Enemy, Inventory, WizardItem, Job, MapFeature, MultipleChoiceQuestion, TrueFalseQuestion, ShopItem, SquireQuestStatus, TeamMessage, TreasureChest, XpThreshold, ChestHint

# Load environment variables at the start of the application
load_dotenv()
recaptcha = os.getenv("RECAPTCHA_SECRET_KEY")

app = Flask(__name__)
app.config["DEBUG"] = True
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your_secret_key')  # For session management

# Database connection function
def get_db_connection():

    try:
        conn = db_session()
        return conn

    except Exception as e:
        logging.error(f"Database connection error: {str(e)}")
        raise

def add_team_message(team_id: int, message: str) -> TeamMessage:
    """
    Persist a new team message and flush it to the database.
    Returns the newly created TeamMessage instance.
    """
    db = db_session()
    try:
        tm = TeamMessage(team_id=team_id, message=message)
        db.add(tm)
        db.commit()        # you can also session.flush() if you want bulk commits later
        db.refresh(tm)     # ensure tm.id and created_at are populated
        return tm
    finally:
        db.close()

def calculate_feature_counts(level, quest_id, base_trees=75, base_mountains=50):
    # Example formula: scale trees and mountains with level and quest
    tree_multiplier = 1 + (level * 0.1) + (quest_id * 0.05)
    mountain_multiplier = 1 + (level * 0.08) + (quest_id * 0.07)

    tree_count = int(base_trees * tree_multiplier)
    mountain_count = int(base_mountains * mountain_multiplier)

    return tree_count, mountain_count

def is_valid_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def send_verification_email(squire_email, squire_name, token):
    try:
        confirm_url = f"https://proffaith.com/verify?token={token}"
        message = Mail(
            from_email='tim@faithatlaw.com',
            to_emails=squire_email,
            subject='🛡️ Confirm your registration for Lawyer’s Quest',
            html_content=f"""
            <p>Hail, noble {squire_name}!</p>
            <p>Thank you for registering for <strong>Lawyer’s Quest</strong>.</p>
            <p>Before you may embark on your legal adventure, you must confirm your email address.</p>
            <p><a href="{confirm_url}">Click here to verify your account</a></p>
            <hr>
            <p>If you did not register for the game, please ignore this message.</p>
            """
        )
        sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
        sg.send(message)
    except Exception as e:
        logging.error(f"SendGrid email error: {e}")


if __name__ == '__main__':
    app.run(port=5050)

#socketio = SocketIO(app)

# 🏠 Homepage (Start Game)

@app.context_processor
def inject_version():
    return {"app_version": flask_session.get("ver", "0.3.3")}

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/team_messages/<int:team_id>")
def get_team_messages(team_id):
    session = db_session()
    since = request.args.get("since")

    query = session.query(TeamMessage).filter(TeamMessage.team_id == team_id)

    if since:
        try:
            # Expect ISO8601 like "2025-04-19T12:34:56"
            ts = datetime.fromisoformat(since)
            query = query.filter(TeamMessage.created_at > ts) \
                         .order_by(TeamMessage.created_at.asc())
        except ValueError:
            session.close()
            return jsonify([])
    else:
        query = query.order_by(TeamMessage.created_at.desc()) \
                     .limit(1)

    msgs = query.all()
    session.close()

    return jsonify([
        {
            "id":          m.id,
            "message":     m.message,
            "created_at":  m.created_at.isoformat()
        }
        for m in msgs
    ])

@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    return render_template('index.html')

@app.route('/getting_started')
def getting_started():
    return render_template('getting_started.html')

@app.route('/select_course/<int:course_id>', methods=['GET'])
def select_course(course_id):
    """Sets the selected course and redirects to quest selection."""

    session["course_id"] = course_id

    #logging.debug(f"🚀 DEBUG: Selected course_id set in session → {session.get('course_id', 'NOT SET')}")
    return redirect(url_for('quest_select'))  # ✅ Refresh quest selection page


# 🔑 Login (Enter Squire ID)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['squire_id']
        db = db_session()
        try:
            # Load the squire by name
            squire = db.query(Squire) \
                       .filter_by(squire_name=username) \
                       .one_or_none()

            if squire:
                # Store in flask session
                flask_session['squire_id']   = squire.id
                flask_session['squire_name'] = squire.squire_name
                flask_session['team_id']     = squire.team_id
                flask_session['level']       = squire.level
                flask_session['ver']         = "0.3.3"

                # Refactored helper should accept the ORM session
                update_riddle_hints()

                return redirect(url_for('quest_select'))

        finally:
            db.close()

    # GET or failed login falls through here
    return render_template('index.html')

@app.route("/register", methods=["GET", "POST"])
def register_squire():

    db=db_session()
    unique = str(uuid.uuid4())

    if request.method == "POST":
        squire_name = request.form["squire_name"]
        real_name = request.form["real_name"]
        email = request.form["email"]
        captcha_response = request.form.get("g-recaptcha-response")
        team_id = int(request.form["team_id"])
        consent = request.form["tos_agree"]

        if consent == "on":
            consent_to_TOS = True


        #logging.debug("🧪 CAPTCHA token received:", captcha_response)

        # Email format check
        if not is_valid_email(email):
            flash("Invalid email format.")
            return redirect(url_for("register_squire"))

        #logging.debug("🌱 FORM DATA:", squire_name, real_name, email, team_id)

        # Validate inputs
        if not squire_name or not real_name or not email or not team_id or consent_to_TOS != True:
            flash("🚫 Please fill out all required fields.")
            return redirect(url_for("register_squire"))

        # Verify CAPTCHA
        captcha_verify_url = "https://www.google.com/recaptcha/api/siteverify"
        response = requests.post(captcha_verify_url, data={
            'secret': recaptcha,
            'response': captcha_response
        })
        result = response.json()

        #logging.debug("📬 CAPTCHA API response:", response.json())

        # After CAPTCHA result:
        #logging.debug("✅ CAPTCHA result:", result)

        if not result.get("success"):
            flash("CAPTCHA verification failed.")
            return redirect(url_for("register_squire"))

        try:
            # 1) Check for duplicate name/email
            name_taken = db.query(Squire).filter(Squire.squire_name == squire_name).count()
            if name_taken:
                flash("Squire name already registered. Click the login link to login with it.")
                return redirect(url_for("register_squire"))

            email_taken = db.query(Squire).filter(Squire.email == email).count()
            if email_taken:
                flash("Your email is already registered. You can login or request an email to recover your squire name.")
                return redirect(url_for("register_squire"))

            # 2) Create the new Squire
            new_squire = Squire(
                squire_name       = squire_name,
                real_name         = real_name,
                email             = email,
                team_id           = team_id,
                experience_points = 0,
                level             = 1,
                x_coordinate      = 0,
                y_coordinate      = 0,
                work_sessions     = 0,
                uuid            = unique,
                consent_to_TOS    = consent_to_TOS
            )
            db.add(new_squire)
            db.commit()
            db.refresh(new_squire)  # now new_squire.id is available

            # 3) Give the starter pizza
            starter_pizza = Inventory(
                squire_id       = new_squire.id,
                item_name       = "🍕 Large Pizza",
                description     = "A starter pizza for your journey.",
                uses_remaining  = 16,
                item_type       = "food"
            )
            db.add(starter_pizza)
            db.commit()

            # 4) Send a Verification Email
            send_verification_email(email, squire_name, unique)


            flash("🎉 Welcome to the realm, noble squire!")
            return redirect(url_for("login"))

        except Exception as e:
            db.rollback()
            logging.warning("❌ DB Error: %s", e)
            flash("🔥 Something went wrong. Please try again.")
            return redirect(url_for("register_squire"))

    else:
        teams = db.query(Team.id, Team.team_name, Team.reputation).all()
        return render_template("register.html", teams=teams)

@app.route("/verify")
def verify_squire():
    db = db_session()
    token = request.args.get("token")

    if not token:
        flash("Missing verification token.")
        return redirect(url_for("login"))

    squire = db.query(Squire).filter_by(uuid=token).first()
    if not squire:
        flash("Invalid or expired token.")
        return redirect(url_for("login"))

    squire.verified_email = True
    db.commit()
    flash("✅ Your squire has been verified. You may now log in.")
    return redirect(url_for("login"))

@app.route("/resend-verification", methods=["POST"])
def resend_verification():
    db = db_session()
    uuid_token = request.form.get("uuid")

    if not uuid_token:
        flash("No token provided.")
        return redirect(url_for("login"))

    try:
        squire = db.query(Squire).filter_by(uuid=uuid_token).first()
        if not squire:
            flash("Invalid token. Please register again.")
            return redirect(url_for("login"))

        if squire.verified_email:
            flash("You are already verified. Feel free to login with your noble Squire name.")
            return redirect(url_for("login"))

        send_verification_email(squire.email, squire.squire_name, squire.uuid)
        flash("📬 A new verification email has been sent!")
        return redirect(url_for("login"))

    except Exception as e:
        logging.warning(f"resend verification error: {e}")
        flash("Could not send verification email. Contact the System Admin to help you.")
        return redirect(url_for("login"))

    finally:
        db.close()



@app.route('/start_quest', methods=['POST'])
def start_quest():
    """Assigns a selected quest to the player."""
    squire_id = flask_session.get("squire_id")
    level = flask_session.get("level")

    if not squire_id:
        return jsonify(success=False, message="Session expired. Please log in again."), 400

    data = request.get_json() or {}
    quest_id = data.get("quest_id")
    if not quest_id:
        return jsonify(success=False, message="Invalid quest selection."), 400

    db = db_session()
    try:
        squire = db.query(Squire).get(squire_id)
        if not squire.verified_email:
            return jsonify(success=False, message="⚠️ You must verify your email before starting quests. Check your inbox or spam folder for the confirmation link."), 403

        # 1) Create the SquireQuestStatus
        sqs = SquireQuestStatus(
            squire_id=squire_id,
            quest_id=quest_id,
            status='active'
        )
        db.add(sqs)
        db.commit()
        db.refresh(sqs)  # now sqs.id is set
        squire_quest_id = sqs.id

        # 2) Fetch the squire's level
        squire = db.query(Squire).get(squire_id)
        level = squire.level

        # 3) Generate terrain features
        treesize, mountainsize = calculate_feature_counts(level, quest_id)
        # Note: adapt these helpers to accept the ORM session and new IDs
        generate_terrain_features_dynamic(
            db, squire_id=squire_id,
            squire_quest_id=squire_quest_id,
            num_forest_clusters=5, cluster_size=10, max_forests=treesize,
            num_mountain_ranges=3, mountain_range_length=9, max_mountains=mountainsize
        )

        # 4) Persist treasure chests and fresh hints
        msg = insert_treasure_chests(
            quest_id=quest_id,
            squire_quest_id=squire_quest_id,
            level=level
        )

        # 5) Store in session and respond
        flask_session["quest_id"]         = quest_id
        flask_session["squire_quest_id"]  = squire_quest_id
        msg += f"\n🛡️ You have started Quest {quest_id}!"

        return jsonify(success=True, message=msg)

    except Exception as e:
        db.rollback()
        logging.warning(f"start quest route error {e}")
        flask_session.pop("quest_id", None)
        flask_session.pop("squire_quest_id", None)
        return jsonify(success=False, message="Failed to start quest."), 500

    finally:
        db.close()

@app.route('/quest_select', methods=['GET'])
def quest_select():
    """Displays available quests for the player to choose from."""
    squire_id = flask_session.get("squire_id")
    if not squire_id:
        return redirect(url_for("login"))

    db = db_session()
    try:
        squire = db.query(Squire).get(squire_id)
        if not squire or not squire.verified_email:
            uuid_token = squire.uuid  # store this BEFORE clearing session
            flask_session.clear()
            flash("⚠️ You must verify your email before selecting a quest. Check your inbox or click below to resend.")
            return redirect(url_for("login", resend_ready="true", uuid=uuid_token))

        # ✅ Fetch all available courses
        courses = db.query(Course).all()

        # Choose course_id from query or session
        course_id = request.args.get("course_id")
        if course_id:
            flask_session['course_id'] = int(course_id)
        else:
            course_id = flask_session.get("course_id")

        quests = []
        if course_id:
            cid = int(course_id)
            # Subquery: quests already completed by this squire
            completed_qids = (
                db.query(SquireQuestStatus.quest_id)
                  .filter_by(squire_id=squire_id, status='completed')
                  .distinct()
                  .subquery()
            )

            # Fetch one active, not-yet-completed quest for this course
            quests = (
                db.query(Quest)
                  .filter(
                      Quest.course_id == cid,
                      Quest.status == 'active',
                      ~Quest.id.in_(completed_qids)
                  )
                  .limit(1)
                  .all()
            )

        # ✅ Retrieve quest completion message (if any)
        quest_message = flask_session.get("quest_message", [])
        logging.debug(f"DEBUG: Quest Message in Session → {quest_message}")
        flask_session.pop("quest_message", None)

        return render_template(
            "quest_select.html",
            courses=courses,
            selected_course_id=course_id,
            quests=quests,
            quest_message=quest_message
        )
    finally:
        db.close()

# 🗺️ Game Map View (Main Game Hub)
@app.route('/map', methods=['GET'])
def map_view():
    squire_id = flask_session.get("squire_id")
    quest_id = flask_session.get("quest_id")
    team_id = flask_session.get('team_id')

    db=db_session()

    if not squire_id:
        return redirect(url_for("login"))

     # ✅ Fetch inventory
    inventory = get_inventory(squire_id)

    try:
        #game_map = display_travel_map(squire_id, quest_id)
        game_map = get_viewport_map(db, squire_id, quest_id,15)
        xp, gold = get_squire_stats(squire_id)
        hunger = get_hunger_bar(squire_id)

        logging.debug("I am on the map just navigating like a navigator does.")

        answered_riddles, total_riddles, progress_percentage = check_quest_progress(squire_id, quest_id)

        progress_bar = display_progress_bar(float(progress_percentage))

        x, y, level = (
            db.query(
                Squire.x_coordinate,
                Squire.y_coordinate,
                Squire.level
            )
            .filter(Squire.id == squire_id)
            .one()
        )

        message = flask_session.pop('message', None)  # Retrieve and clear messages after displaying

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

#NPC interactions
@app.route('/npc', methods=['GET'])
def npc():
    """Handles Wandering Trader encounters and displays hints."""
    npc_message = flask_session.pop("npc_message", "The trader has no hints for you.")
    return render_template("npc.html", npc_message=npc_message)

@app.route('/blacksmith', methods=['GET', 'POST'])
def blacksmith():
    squire_id = flask_session['squire_id']
    db = db_session()
    # load squire and inventory items that need repair:
    squire = db.query(Squire).get(squire_id)
    team = db.query(Team).get(squire.team_id)  # or use a relationship if defined
    level = squire.level

    max_uses = level * 4

    broken_items = (
        db.query(Inventory)
        .filter(
            Inventory.squire_id == squire_id,
            Inventory.item_type == "gear",
            ~Inventory.description.ilike("%magical%"),
            Inventory.uses_remaining < max_uses
        )
        .all()
    )

    # In your route (after defining broken_items)
    item_info = [
        {
            "id": item.id,
            "name": item.item_name,
            "uses_remaining": item.uses_remaining,
            "max_uses": max_uses  # or item-specific if using a property
        }
        for item in broken_items
    ]


    if request.method == 'POST':
        item_id   = int(request.form['item_id'])
        pay_amount= int(request.form['bitcoin'])
        item = db.query(Inventory).get(item_id)

        # sanity checks
        if pay_amount <= 0 or pay_amount > team.gold:
            flash("Invalid payment amount.", "error")
            return redirect(url_for('blacksmith'))

        # e.g. 1 bitcoin = 1 use repaired
        repaired_uses = pay_amount
        item.uses_remaining = min(50, item.uses_remaining + repaired_uses)
        team.gold -= pay_amount

        db.commit()
        flash(f"Your {item.item_name} regained {repaired_uses} uses!", "success")
        return redirect(url_for('map_view'))

    return render_template('blacksmith.html',
                           squire=squire,
                           team=team,
                           broken_items=broken_items,
                           item_info=item_info)

@app.route('/wandering_trader', methods=['GET', 'POST'])
def wandering_trader():
    squire_id = flask_session.get('squire_id')
    db = db_session()
    squire = db.query(Squire).get(squire_id)
    team = db.query(Team).get(squire.team_id)

    if request.method == 'POST':
        item_id = int(request.form['item_id'])
        shop_item = db.query(ShopItem).get(item_id)

        if shop_item.price > team.gold:
            flash("You can't afford that!", "error")
            return redirect(url_for('wandering_trader'))

        team.gold -= shop_item.price
        db.add(Inventory(
            squire_id = squire.id,
            item_name = shop_item.item_name,
            description = shop_item.description,
            uses_remaining = shop_item.uses,
            item_type = shop_item.item_type
        ))
        db.commit()
        flash(f"You bought {shop_item.item_name} for {shop_item.price} bits!", "success")
        return redirect(url_for('map_view'))

    trader_items = (
    db.query(ShopItem)
        .filter(
            ShopItem.available_to_trader == True,
            ShopItem.min_level <= squire.level  # Only show items at or below the squire's level
        )
        .order_by(func.rand())
        .limit(3)
        .all()
    )

    item_info = [
        {
            "id": item.id,
            "name": item.item_name,
            "price": item.price,
            "description": item.description,
            "uses": item.uses,
            "item_type": item.item_type
        }
        for item in trader_items
    ]

    return render_template("wandering_trader.html",
                           squire=squire,
                           team=team,
                           items=trader_items,
                           item_info=item_info)


# 🚶 Game Actions (Movement, Shop, Town, Combat)
# mod for AJAX
@app.route('/ajax_move', methods=['POST'])
def ajax_move():
    event = None
    message = ""
    x = y = tm = None

    squire_id = flask_session.get("squire_id")
    quest_id = flask_session.get("quest_id")
    squire_quest_id = flask_session.get("squire_quest_id")
    db=db_session()

    if not squire_id:
        return jsonify({"error": "Session expired. Please log in again."}), 400

    direction = request.json.get("direction")  # Get movement direction from AJAX request

    level = db.query(Squire.level).filter(Squire.id == squire_id).scalar()

    # **Check if movement is valid (including food requirement)**
    if direction in ["N", "S", "E", "W", "V", "I"]:

        if direction == "I":
            event = "inventory"
            return jsonify({"redirect": url_for("inventory"), "message": message})

        x, y, tm = update_player_position(db, squire_id, direction)

        if direction in ["N", "S", "E", "W"]:
            ok, food_message = consume_food(squire_id)
            if not ok:
                # If no food available, return the message immediately (or handle it as needed)
                message = f"{food_message} \n {tm}"
                return jsonify({"message": message})

            # Otherwise, include the food message in your response
            else:
                message = f"{food_message} \n {tm}"


            p = calculate_enemy_encounter_probability(squire_id, quest_id, x,y,  squire_quest_id)
            logging.debug(f"Combat Probability: {p}")

        if check_quest_completion(squire_id, quest_id):
            flask_session["quest_completed"] = True
            completed, messages = complete_quest(squire_id, quest_id)

            if completed:
                for msg in messages:
                    flash(msg, "success")  # or use "quest" if you're styling categories

                return jsonify({"redirect": url_for("quest_select"),
                    "position": (x,y),
                    "message": message
                    })

        if direction == "V":
            x,y,tm = update_player_position(db, squire_id, direction)
            visit_town()
            message = "🏰 You arrive in Bitown."
            return jsonify({
                "redirect": url_for("visit_town"),
                "position": (x,y),
                "message": message
                })



        # 🔥 Boss Fight Check: if on quest 14 and reached (40,40), trigger the boss fight!
        if quest_id == 14 and x == 40 and y == 40:
            logging.debug("🏰 Boss fight triggered! Player reached (40,40) during quest 14.")
            # Optionally call a function to set up boss fight state:
            #initiate_boss_fight(squire_id, quest_id)  # define this function as needed
            event = "q14bossfight"

            return jsonify({
                "boss_fight": True,
                "message": "You have reached the stronghold! Prepare to face the boss!",
                "position": (x,y),
                "event": event
            })

        if x == 0 and y ==0:
            x,y,tm = update_player_position(db, squire_id, direction)
            visit_town()
            message = "🏰 You arrive in Bitown."
            return jsonify({"redirect": url_for("visit_town"), "message": message})

        # ✅ Generate Updated Map
        #game_map = display_travel_map(squire_id, quest_id)
        game_map = get_viewport_map(db, squire_id, quest_id,  15)

        if not game_map:
            logging.error("❌ ERROR: display_travel_map() returned None!")
            return jsonify({"error": "Failed to load the updated map."}), 500

        # **🎁 Treasure Check**
        chest = check_for_treasure_at_location(squire_id, x, y,  quest_id, squire_quest_id)
        if chest:
            logging.debug(f"Found a treasure chest at {x},{y}.")
            flask_session["current_treasure_id"] = chest.id  # Store chest in session
            event = "treasure"
            # before you db.add(...)
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
                # already got that hint—do nothing (or log if you care)
                logging.debug("👍 ChestHint already recorded for that location.")

        else:

            # Step 1: Build a list of eligible events
            eligible_events = []

            # 🏞️ NPC Encounter
            if random.random() < 0.02:
                eligible_events.append("npc")

            if random.random() < 0.02:
                eligible_events.append("npc_trader")

            # 🧙‍♂️ Riddle Encounter
            if random.random() < 0.03:
                eligible_events.append("riddle")

            # ⚔️ Combat
            if random.random() < p:
                eligible_events.append("enemy")

            if random.random() < 0.03 and level > 3:
                eligible_events.append("blacksmith")

            if eligible_events:
                event = random.choice(eligible_events)


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
                            SquireRiddleProgress.squire_id   == squire_id
                        )
                    )
                    .filter(
                        SquireRiddleProgress.riddle_id  == None,           # not yet answered
                        Riddle.quest_id                  == quest_id,
                        TreasureChest.is_opened          == False,
                        TreasureChest.squire_quest_id    == squire_quest_id
                    )
                    .order_by(func.rand())  # MySQL’s RAND()
                    .limit(1)
                    .first()
                )

                if coords:
                    chest_x, chest_y = coords
                    message = f"🌿 A wandering trader appears: 'There's a chest at ({chest_x},{chest_y}). I tried to open it but couldn't figure out the riddle. Good luck!'"
                    flask_session['npc_message'] = message
                    flask_session.modified = True
                    logging.debug(f"NPC Message Set: {message}")  # Debugging
                    db.add(ChestHint(
                        squire_quest_id = squire_quest_id,
                        chest_x = chest_x,
                        chest_y = chest_y
                    ))
                    db.commit()

                event = "npc"

            elif event == "riddle":
                pass  # Your riddle logic

            elif event == "enemy":
                pass  # Your combat setup logic

            elif event == "blacksmith":
                return jsonify({"redirect": url_for("blacksmith"), "message": message})

            elif event == "npc_trader":
                return jsonify({"redirect": url_for("wandering_trader"), "message": message})

    # **Build JSON Response**
    response_data = {
        "map": game_map,
        "message": message,
        "position": (x,y),
        "event": event  # Pass event type
    }

    return jsonify(response_data)

@app.route('/ajax_status', methods=['GET'])
def ajax_status():
    squire_id = flask_session.get("squire_id")
    quest_id = flask_session.get("quest_id")
    db = db_session()

    if not squire_id:
        return jsonify({"error": "Not logged in"}), 403

    x, y, level = (
        db.query(
            Squire.x_coordinate,
            Squire.y_coordinate,
            Squire.level
        )
        .filter(Squire.id == squire_id)
        .one()
    )

    inventory = get_inventory(squire_id)
    hunger = get_hunger_bar(squire_id)
    xp, gold = get_squire_stats(squire_id)

    answered_riddles, total_riddles, progress_percentage = check_quest_progress(squire_id, quest_id)
    progress_bar = display_progress_bar(float(progress_percentage))

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
    squire_id = flask_session.get("squire_id")

    if not squire_id:
        return redirect(url_for("login"))

    conn = get_db_connection()
    inventory = get_inventory(squire_id)  # Fetch inventory items

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
    squire_id = flask_session.get("squire_id")
    quest_id  = flask_session.get("quest_id")
    enemy     = flask_session.get("enemy", {})
    has_weapon= enemy.get("has_weapon", False)
    win_msg = []

    if not all([squire_id, quest_id, enemy]):
        return jsonify(success=False,
                       message="Session expired. Please log in again."), 400

    db = db_session()
    try:
        # 1) Fetch a random True/False question not yet seen twice
        #    (assumes your SquireQuestion model has a times_encountered field)
        tq = (
            db.query(
                TrueFalseQuestion.id,
                TrueFalseQuestion.question,
                TrueFalseQuestion.correct_answer
            )
            .outerjoin(
                SquireQuestion,
                and_(
                    SquireQuestion.question_id == TrueFalseQuestion.id,
                    SquireQuestion.squire_id  == squire_id
                )
            )
            .filter(
                TrueFalseQuestion.quest_id == quest_id,
                # either never seen or seen fewer than 2 times
                (SquireQuestion.times_encountered == None) |
                (SquireQuestion.times_encountered < 2)
            )
            .order_by(func.rand())
            .first()
        )

        # 2) No question available
        if not tq:
            if not has_weapon:
                # force flee: lose XP and damage gear
                degrade_gear(squire_id, "zip")
                squire = db.query(Squire).get(squire_id)
                squire.experience_points = max(0, squire.experience_points - 10)
                db.commit()

                flee_msg = (
                    "🛑 The enemy forces you to flee because you are unarmed.\n"
                    "❌ You lose 10 XP and your gear is damaged."
                )
                flask_session['message'] = flee_msg

                return jsonify(
                    success=False,
                    message=flee_msg,
                    flee=True
                )

            # armed but no question left
            return jsonify(
                success=False,
                message="❌ No question available. You must fight!",
                redirect=url_for("ajax_handle_combat")
            )

        # 3) Validate answer
        user_answer = request.json.get("answer", "").strip().upper()
        if user_answer not in ("T", "F"):
            return jsonify(
                success=False,
                message="Invalid answer. Please submit 'T' or 'F'."
            ), 400

        correct_bool = bool(tq.correct_answer)
        is_correct = (user_answer == "T" and correct_bool) or \
                     (user_answer == "F" and not correct_bool)

        # 4) Handle correct
        if is_correct:
            xp_gain   = enemy['xp_reward']
            gold_gain = enemy['gold_reward']
            win_msg.append(update_squire_progress(db, squire_id, xp_gain, gold_gain))

            win_msg.append (
                f"✅ Correct! The enemy is defeated! "
                f"You gain {xp_gain} XP and {gold_gain} bits."
            )
            flask_session['message'] = win_msg

            # Broadcast to team
            toast = (
                f"{flask_session['squire_name']} defeated "
                f"{enemy['name']} and gained {xp_gain} XP "
                f"and {gold_gain} bits."
            )
            add_team_message(flask_session['team_id'], toast)

            db.commit()

            return jsonify(
                success=True,
                message=win_msg,
                xp_reward=xp_gain,
                gold_reward=gold_gain,
                defeated=True
            )

        # 5) Handle incorrect
        if has_weapon:
            # still armed, can retry/fight
            return jsonify(
                success=False,
                message="❌ Wrong answer! En Garde!",
                redirect=url_for("ajax_handle_combat")
            )

        # unarmed & wrong: forced to flee
        degrade_gear(squire_id, "zip")
        squire = db.query(Squire).get(squire_id)
        squire.experience_points = max(0, squire.experience_points - 10)
        db.commit()

        flee_msg = (
            "🛑 The enemy forces you to flee by your wrong answer.\n"
            "❌ You lose 10 XP and your gear is damaged."
        )
        flask_session['message'] = flee_msg

        return jsonify(
            success=False,
            message=flee_msg,
            flee=True
        )

    finally:
        db.close()

@app.route('/answer_question', methods=['GET'])
def answer_question():
    """Displays a True/False question before the player submits an answer."""
    squire_id = flask_session.get("squire_id")
    quest_id  = flask_session.get("quest_id")
    level = flask_session.get("level")
    pending_job  = flask_session.get("pending_job")

    if not (squire_id and quest_id):
        return redirect(url_for('login'))

    db = db_session()

    if pending_job:
        if pending_job["job_id"] > 2:
            question_type = random.choice(["true_false", "multiple_choice"])
        else:
            question_type = "true_false"

    else:
        enemy = flask_session.get("enemy")
        enemylevel = enemy["min_level"]

        if level > 2 and enemylevel > 2:
            question_type = random.choice(["true_false", "multiple_choice"])
        else:
            question_type = "true_false"

    if question_type == "true_false":
        try:
            # 1) Total questions in this quest
            total_qs = (
                db.query(TrueFalseQuestion)
                  .filter(TrueFalseQuestion.quest_id == quest_id)
                  .count()
            )

            # 2) Which question_ids has this squire already encountered?
            answered_rows = (
                db.query(SquireQuestion.question_id)
                  .filter(
                      SquireQuestion.squire_id   == squire_id,
                      SquireQuestion.question_type == 'true_false'
                  )
                  # only consider those tied to this quest
                  .join(TrueFalseQuestion,
                        SquireQuestion.question_id == TrueFalseQuestion.id)
                  .filter(TrueFalseQuestion.quest_id == quest_id)
                  .all()
            )
            answered_ids = {qid for (qid,) in answered_rows}
            answered_count = len(answered_ids)

            # 3) Build the base query
            q = (
                db.query(
                    TrueFalseQuestion.id,
                    TrueFalseQuestion.question,
                    TrueFalseQuestion.correct_answer
                )
                .filter(TrueFalseQuestion.quest_id == quest_id)
            )

            # 4) If not yet answered all, exclude those already seen
            if answered_count < total_qs:
                q = q.filter(~TrueFalseQuestion.id.in_(answered_ids))

            # 5) Grab a random one
            question_row = q.order_by(func.rand()).first()

            # 6) No question left?
            if not question_row:
                flask_session["battle_summary"] = "No question available. You must fight!"
                return redirect(url_for("ajax_handle_combat"))

            # 7) Store for validation and render
            flask_session["current_question"] = {
                "id":   question_row.id,
                "text": question_row.question
            }
            return render_template(
                "answer_question.html",
                question={
                    "id":   question_row.id,
                    "question": question_row.question,
                    # note: template probably doesn’t need correct_answer
                }
            )
        finally:
            db.close()

    else:
        # Grab answered multiple choice question IDs
        mc_answered_rows = (
            db.query(SquireQuestion.question_id)
              .filter(
                  SquireQuestion.squire_id == squire_id,
                  SquireQuestion.question_type == 'multiple_choice'
              )
              .join(MultipleChoiceQuestion,
                    SquireQuestion.question_id == MultipleChoiceQuestion.id)
              .filter(MultipleChoiceQuestion.quest_id == quest_id)
              .all()
        )
        mc_answered_ids = {qid for (qid,) in mc_answered_rows}
        mc_total_qs = (
            db.query(MultipleChoiceQuestion)
              .filter(MultipleChoiceQuestion.quest_id == quest_id)
              .count()
        )
        mc_q = (
            db.query(
                MultipleChoiceQuestion.id,
                MultipleChoiceQuestion.question_text,
                MultipleChoiceQuestion.optionA,
                MultipleChoiceQuestion.optionB,
                MultipleChoiceQuestion.optionC,
                MultipleChoiceQuestion.optionD,
                MultipleChoiceQuestion.correctAnswer
            )
            .filter(MultipleChoiceQuestion.quest_id == quest_id)
        )
        if len(mc_answered_ids) < mc_total_qs:
            mc_q = mc_q.filter(~MultipleChoiceQuestion.id.in_(mc_answered_ids))

        mc_question = mc_q.order_by(func.rand()).first()
        if not mc_question:
            flask_session["battle_summary"] = "No question available. You must fight!"
            return redirect(url_for("ajax_handle_combat"))

        flask_session["current_question"] = {
            "id": mc_question.id,
            "text": mc_question.question_text,
            "type": "multiple_choice",
            "options": {
                "A": mc_question.optionA,
                "B": mc_question.optionB,
                "C": mc_question.optionC,
                "D": mc_question.optionD
            }
        }
        return render_template("answer_question_mc.html", question=flask_session["current_question"])

@app.route('/check_true_false_question', methods=['POST'])
def check_true_false_question():
    """Validates the player's True/False answer."""
    squire_id    = flask_session.get("squire_id")
    question_id  = request.form.get("question_id")
    user_answer  = request.form.get("answer", "").strip().upper()
    enemy        = flask_session.get("enemy", {})
    pending_job  = flask_session.pop("pending_job", None)
    flask_session.pop("success", None)
    toast =[]

    if not (squire_id and question_id):
        flask_session["battle_summary"] = "Error: Missing session or question."
        return redirect(url_for("combat_results"))

    db = db_session()
    try:
        # 1) Load question
        q = db.query(TrueFalseQuestion).get(int(question_id))
        if not q:
            flask_session["battle_summary"] = "Error: Question not found."
            return redirect(url_for("combat_results"))

        correct_int = 1 if q.correct_answer else 0
        user_int    = 1 if user_answer == "T" else 0

        logging.debug(f"TF Check: squire={squire_id}, qid={question_id}, "
                      f"user={user_int}, correct={correct_int}")

        # 2) Record as answered correctly if matches
        if user_int == correct_int:
            sq = (
                db.query(SquireQuestion)
                  .filter_by(
                      squire_id=squire_id,
                      question_id=q.id,
                      question_type='true_false'
                  )
                  .one_or_none()
            )
            if not sq:
                sq = SquireQuestion(
                    squire_id=squire_id,
                    question_id=q.id,
                    question_type='true_false',
                    answered_correctly=True
                )
                db.add(sq)
            else:
                sq.answered_correctly = True
            db.commit()

            # 3a) Pending job payout
            if pending_job:
                squire = db.query(Squire).get(squire_id)
                level  = squire.level
                payout = random.randint(
                    pending_job["min_payout"],
                    pending_job["max_payout"]
                ) * level

                # Pay team
                team = db.query(Team).get(squire.team_id)
                team.gold += payout
                # Increment work sessions
                squire.work_sessions += 1

                db.commit()

                msg = (f"✅ You completed '{pending_job['job_name']}' "
                       f"and earned 💰 {payout} bits!")
                flask_session["job_message"] = msg

                toast.append (f"{flask_session['squire_name']} completed "
                         f"'{pending_job['job_name']}' and earned 💰 {payout} bits.")
                add_team_message(squire.team_id, toast)

                return redirect(url_for("visit_town"))

            # 3b) Combat reward
            flask_session["forced_combat"] = False
            xp_gain   = enemy.get("xp_reward", 0)
            gold_gain = enemy.get("gold_reward", 0)
            toast.append(update_squire_progress(squire_id, xp_gain, gold_gain))

            toast.append (
                f"{flask_session['squire_name']} defeated "
                f"{enemy.get('name')} and gained "
                f"{xp_gain} XP and {gold_gain} bits."
            )
            message = " ".join([str(m) for m in toast if m])
            add_team_message(flask_session['team_id'], message)
            db.commit()

            flask_session["combat_result"] = (
                f"✅ Correct! You have defeated the enemy "
                f"and earned {xp_gain} XP and {gold_gain} bits."
            )
            flask_session["success"] = True

        else:
            # 4) Incorrect answer handling
            if question_id:
                question = db.query(TrueFalseQuestion).get(question_id)
                hint = question.hint if question else None
            else:
                hint = None

            if pending_job:
                flask_session["job_message"] = (
                    f"❌ Incorrect! You failed the task and earned nothing but this hint: {hint}."
                )
                return redirect(url_for("visit_town"))

            # Damage gear and penalize XP
            degrade_gear(squire_id, enemy.get("weakness"))
            squire = db.query(Squire).get(squire_id)
            squire.experience_points = max(
                0,
                squire.experience_points - enemy.get("xp_reward", 0)
            )
            db.commit()

            flask_session["combat_result"] = (
                f"❌ Incorrect! You are defeated by "
                f"{enemy.get('name')} and lose some experience points! \n"
                f"{hint}"
            )
            flask_session["success"] = False

        # 5) Show results
        return render_template(
            "combat_results.html",
            success=flask_session.pop("success", None),
            combat_result=flask_session.pop("combat_result", "")
        )
    finally:
        db.close()

@app.route('/check_MC_question_enemy', methods=['POST'])
def check_MC_question_enemy():
    """Validates the player's True/False answer."""
    squire_id    = flask_session.get("squire_id")
    question_id  = request.form.get("question_id")
    user_answer  = request.form.get("answer", "").strip().upper()
    enemy        = flask_session.get("enemy", {})
    pending_job  = flask_session.pop("pending_job", None)
    flask_session.pop("success", None)
    toast =[]

    if not (squire_id and question_id):
        flask_session["battle_summary"] = "Error: Missing session or question."
        return redirect(url_for("combat_results"))

    db = db_session()

    logging.debug(f"Check_MC_question qid/user_answer {question_id}/{user_answer}")

    try:
        # 1) Load the MC question
        mcq = db.query(MultipleChoiceQuestion).get(question_id)
        if not mcq:
            flask_session["battle_summary"] = "Error: Question not found."
            return redirect(url_for("combat_results"))

        # 2) Determine correctness
        correct = (user_answer == mcq.correctAnswer)

        # 3) Record attempt if correct
        if correct:
            # Upsert SquireQuestion
            sq = (
                db.query(SquireQuestion)
                  .filter_by(
                      squire_id=squire_id,
                      question_id=mcq.id,
                      question_type='multiple_choice'
                  )
                  .one_or_none()
            )
            if not sq:
                sq = SquireQuestion(
                    squire_id=squire_id,
                    question_id=mcq.id,
                    question_type='multiple_choice',
                    answered_correctly=True
                )
                db.add(sq)
            else:
                sq.answered_correctly = True
            db.commit()

            # 3a) Pending job payout
            if pending_job:
                squire = db.query(Squire).get(squire_id)
                level  = squire.level
                payout = random.randint(
                    pending_job["min_payout"],
                    pending_job["max_payout"]
                ) * level

                # Pay team
                team = db.query(Team).get(squire.team_id)
                team.gold += payout
                # Increment work sessions
                squire.work_sessions += 1

                db.commit()

                msg = (f"✅ You completed '{pending_job['job_name']}' "
                       f"and earned 💰 {payout} bits!")
                flask_session["job_message"] = msg

                toast.append (f"{flask_session['squire_name']} completed "
                         f"'{pending_job['job_name']}' and earned 💰 {payout} bits.")
                add_team_message(squire.team_id, toast)

                return redirect(url_for("visit_town"))

            # 3b) Combat reward
            flask_session["forced_combat"] = False
            xp_gain   = enemy.get("xp_reward", 0)
            gold_gain = enemy.get("gold_reward", 0)
            toast.append(update_squire_progress(squire_id, xp_gain, gold_gain))

            toast.append (
                f"{flask_session['squire_name']} defeated "
                f"{enemy.get('name')} and gained "
                f"{xp_gain} XP and {gold_gain} bits."
            )
            message = " ".join([str(m) for m in toast if m])
            add_team_message(flask_session['team_id'], message)
            db.commit()

            flask_session["combat_result"] = (
                f"✅ Correct! You have defeated the enemy "
                f"and earned {xp_gain} XP and {gold_gain} bits."
            )
            flask_session["success"] = True

            return redirect(url_for("combat_results"))

        else:
            if question_id:
                question = db.query(MultipleChoiceQuestion).get(question_id)
                hint = question.hint if question else None
            else:
                hint = None

            if pending_job:
                flask_session["job_message"] = (
                    f"❌ Incorrect! You failed the task and earned nothing except this hint: {hint}."
                )
                return redirect(url_for("visit_town"))

            # Damage gear and penalize XP
            degrade_gear(squire_id, enemy.get("weakness"))
            squire = db.query(Squire).get(squire_id)
            squire.experience_points = max(
                0,
                squire.experience_points - enemy.get("xp_reward", 0)
            )
            db.commit()

            flask_session["combat_result"] = (
                f"❌ Incorrect! You are defeated by "
                f"{enemy.get('name')} and lose some experience points! \n"
                f"{hint}"
            )
            flask_session["success"] = False

        return render_template(
            "combat_results.html",
            success=flask_session.pop("success", None),
            combat_result=flask_session.pop("combat_result", ""))

    finally:
        db.close()

# ⚔️ Combat
@app.route('/combat', methods=['GET', 'POST'])
def combat():
    """Displays combat screen where player chooses to fight or flee."""
    enemy = flask_session.get('enemy')
    squire_id = flask_session.get("squire_id")
    db=db_session()

    if not enemy:
        logging.debug("No enemy found in session, redirecting to map.")
        return redirect(url_for('map_view'))  # No enemy data? Go back to map.

    x, y, level = (
        db.query(
            Squire.x_coordinate,
            Squire.y_coordinate,
            Squire.level
        )
        .filter(Squire.id == squire_id)
        .one()
    )

    #return necessary initial values for combat
    update_work_for_combat(squire_id)
    max_hunger, food = get_player_max_hunger(squire_id)
    base_hit_chance = calculate_hit_chance(squire_id, level)
    hit_chance = int(min(base_hit_chance + combat_mods(squire_id, enemy["name"], level), 95))
    player_max_hunger = min(max_hunger + hunger_mods(squire_id), 8)


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
    battle_log = flask_session.get("battle_log", [])

    # Save updated values in session
    flask_session["player_current_hunger"] = player_current_hunger
    flask_session["enemy_current_hunger"] = enemy_current_hunger
    flask_session["player_max_hunger"] = player_max_hunger
    flask_session["mod_enemy_max_hunger"] = mod_enemy_max_hunger
    flask_session["hit_chance"] = hit_chance
    flask_session["mod_for_distance"] = mod_for_distance
    flask_session["safe_chances"] = safe_chances

    return render_template('combat.html', enemy=enemy)

@app.route('/encounter_enemy', methods=['GET'])
def encounter_enemy():
    """Handles an enemy encounter with a choice between knowledge and combat."""
    squire_id = flask_session.get("squire_id")
    if not squire_id:
        return redirect(url_for("login"))

    db = db_session()
    try:
        # 1) Get squire position and level
        x, y, level = (
            db.query(
                Squire.x_coordinate,
                Squire.y_coordinate,
                Squire.level
            )
            .filter(Squire.id == squire_id)
            .one()
        )

        # 2) Determine terrain
        in_forest = (
            db.query(func.count(MapFeature.id))
              .filter(
                  MapFeature.x_coordinate == x,
                  MapFeature.y_coordinate == y,
                  MapFeature.terrain_type  == 'forest'
              )
              .scalar() > 0
        )
        in_mountain = (
            db.query(func.count(MapFeature.id))
              .filter(
                  MapFeature.x_coordinate == x,
                  MapFeature.y_coordinate == y,
                  MapFeature.terrain_type  == 'mountain'
              )
              .scalar() > 0
        )

        # 3) Pick a random non‑boss enemy appropriate to level
        enemy = (
            db.query(Enemy)
              .filter(
                  Enemy.is_boss   == False,
                  Enemy.min_level <= level
              )
              .order_by(func.rand())
              .first()
        )

        if enemy:
            # 4) Check for required weapon in inventory
            has_weapon = (
                db.query(func.count(Inventory.id))
                  .filter(
                      Inventory.squire_id == squire_id,
                      Inventory.item_name   == enemy.weakness
                  )
                  .scalar() > 0
            )

            # 5) Store JSON‑safe enemy data in session
            flask_session['enemy'] = {
                "id":           enemy.id,
                "name":         enemy.enemy_name,
                "description":  enemy.description,
                "weakness":     enemy.weakness,
                "gold_reward":  enemy.gold_reward,
                "xp_reward":    enemy.xp_reward,
                "max_hunger":   enemy.max_hunger,
                "in_forest":    in_forest,
                "in_mountain":  in_mountain,
                "has_weapon":   has_weapon,
                "static_image": enemy.static_image,
                "min_level": enemy.min_level
            }

        return redirect(url_for('combat'))

    finally:
        db.close()

@app.route('/encounter_boss', methods=['GET'])
def encounter_boss():
    squire_id = flask_session.get("squire_id")
    if not squire_id:
        return redirect(url_for("login"))

    db = db_session()
    try:
        # 1) Fetch squire’s position & level
        x, y, level = (
            db.query(
                Squire.x_coordinate,
                Squire.y_coordinate,
                Squire.level
            )
            .filter(Squire.id == squire_id)
            .one()
        )

        # 2) Fetch the boss by name pattern
        boss = (
            db.query(Enemy)
              .filter(Enemy.enemy_name.ilike("%Lexiconis%"))
              .first()
        )

        if boss:
            # 3) Store JSON‑safe boss data in session
            flask_session['boss'] = {
                "id":           boss.id,
                "name":         boss.enemy_name,
                "description":  boss.description,
                "weakness":     boss.weakness,
                "gold_reward":  boss.gold_reward,
                "xp_reward":    boss.xp_reward,
                "max_hunger":   boss.max_hunger
            }

        return redirect(url_for('boss_combat'))

    finally:
        db.close()

@app.route('/boss_combat', methods=['GET', 'POST'])
def boss_combat():
    """Displays combat screen where player chooses to fight or flee."""
    boss = flask_session.get('boss')
    squire_id = flask_session.get("squire_id")
    quest_id = flask_session.get("quest_id")

    if not boss:
        logging.debug("Guess the boss is out to lunch: redirecting to map.")
        return redirect(url_for('map_view'))  # No enemy data? Go back to map.

    x, y, level = (
        db.query(
            Squire.x_coordinate,
            Squire.y_coordinate,
            Squire.level
        )
        .filter(Squire.id == squire_id)
        .one()
    )

    max_hunger, food = get_player_max_hunger(squire_id)
    player_max_hunger = min(max_hunger + hunger_mods(squire_id), 8)
    boss_max_hunger = boss["max_hunger"]

    # initialize session variables for battle
    if flask_session.get("player_current_hunger") is None:
        session["player_current_hunger"] = 0
    if flask_session.get("boss_current_hunger") is None:
        session["boss_current_hunger"] = 0

    session["player_max_hunger"] = int(player_max_hunger)
    session["boss_max_hunger"] = int(boss_max_hunger)

    return render_template('boss_combat.html', boss=boss)

@app.route('/ajax_handle_boss_combat', methods=['POST', 'GET'])
def ajax_handle_boss_combat():
    """Handles combat via AJAX by updating hunger levels and returning JSON."""
    boss = flask_session.get("boss")
    squire_id = flask_session.get("squire_id")

    if not boss or not squire_id:
        logging.error("Missing boss or squire_id in session")
        return jsonify({"redirect": url_for("map_view")})

    try:
        player_current_hunger = flask_session.get("player_current_hunger", 0)
        boss_current_hunger = flask_session.get("boss_current_hunger", 0)
        player_max_hunger = flask_session.get("player_max_hunger", 0)
        boss_max_hunger = flask_session.get("boss_max_hunger", 0)


        logging.debug(f"Boss Status: {boss_current_hunger} / {boss_max_hunger} Player Status {player_current_hunger} / {player_max_hunger}")

        # route based on the button pushed by the user
        action = request.form.get("action")

        if action == "flee":
            if flee_safely(boss_max_hunger, player_max_hunger, 0) == False:
                session["combat_result"] = "🏃 You managed to escape safely!"
            else:
                degrade_gear(squire_id, boss["weakness"])
                session["combat_result"] = "🏃 You managed to escape but your armor was damaged during the retreat."
            # Clear session combat variables
            cleanup_session()
            return jsonify({"redirect": url_for("combat_results")})

        else: #answer questions
            return jsonify({"redirect": url_for("answer_MC_question")})

    except Exception as e:
        logging.error(f"Error in boss combat: {str(e)}")
        return jsonify({"error": "An error occurred during combat"}), 500


#present questions
@app.route('/answer_MC_question', methods=['GET'])
def answer_MC_question():
    """Displays a random multiple‐choice question for boss combat."""
    boss       = flask_session.get('boss')
    squire_id  = flask_session.get("squire_id")
    quest_id   = flask_session.get("quest_id")

    if not (boss and squire_id and quest_id):
        return redirect(url_for("login"))

    # pull in hunger if needed elsewhere
    player_current_hunger = flask_session.get("player_current_hunger")
    boss_current_hunger   = flask_session.get("boss_current_hunger")

    db = db_session()
    try:
        # 1) Find which MC questions this squire has already seen
        answered_rows = (
            db.query(SquireQuestion.question_id)
              .filter(
                  SquireQuestion.squire_id    == squire_id,
                  SquireQuestion.question_type == 'multiple_choice'
              )
              .all()
        )
        answered_ids = {qid for (qid,) in answered_rows}

        # 2) Fetch a random MCQ with quest_id < current and not yet seen
        mcq = (
            db.query(MultipleChoiceQuestion)
              .filter(
                  MultipleChoiceQuestion.quest_id < quest_id,
                  ~MultipleChoiceQuestion.id.in_(answered_ids)
              )
              .order_by(func.rand())
              .first()
        )

        if not mcq:
            flask_session["battle_summary"] = "No question available. You must flee!"
            return redirect(url_for("ajax_handle_boss_combat"))

        # 3) Store for validation in session
        flask_session["current_question"] = {
            "id":            mcq.id,
            "text":          mcq.question_text,
            "optionA":       mcq.optionA,
            "optionB":       mcq.optionB,
            "optionC":       mcq.optionC,
            "optionD":       mcq.optionD,
            "correctAnswer": mcq.correctAnswer
        }

        return render_template('boss_combat.html', boss=boss)

    finally:
        db.close()


#then need a route to check if the question was answered correctly so that that can be recorded as either
#increasing the player's hunger or the enemy's hunger
@app.route('/check_MC_question', methods=['POST'])
def check_MC_question():
    """Validates the player's multiple-choice answer for boss combat."""
    boss               = flask_session.get('boss', {})
    squire_id          = flask_session.get('squire_id')
    question_id        = request.form.get("question_id", type=int)
    user_answer        = request.form.get("selected_option")
    player_hunger      = flask_session.get("player_current_hunger", 0)
    boss_hunger        = flask_session.get("boss_current_hunger", 0)
    player_max_hunger  = flask_session.get("player_max_hunger", 0)
    boss_max_hunger    = flask_session.get("boss_max_hunger", 0)

    logging.debug(f"Check_MC_question qid/user_answer {question_id}/{user_answer}")
    db = db_session()
    try:
        # 1) Load the MC question
        mcq = db.query(MultipleChoiceQuestion).get(question_id)
        if not mcq:
            flask_session["battle_summary"] = "Error: Question not found."
            return redirect(url_for("combat_results"))

        # 2) Determine correctness
        correct = (user_answer == mcq.correctAnswer)

        # 3) Record attempt if correct
        if correct:
            # Upsert SquireQuestion
            sq = (
                db.query(SquireQuestion)
                  .filter_by(
                      squire_id=squire_id,
                      question_id=mcq.id,
                      question_type='multiple_choice'
                  )
                  .one_or_none()
            )
            if not sq:
                sq = SquireQuestion(
                    squire_id=squire_id,
                    question_id=mcq.id,
                    question_type='multiple_choice',
                    answered_correctly=True
                )
                db.add(sq)
            else:
                sq.answered_correctly = True
            db.commit()

            # 4a) Increase boss hunger
            boss_hunger += 1
            flask_session["boss_current_hunger"] = boss_hunger
            flask_session["question_id"] = None
            enemy_message = f"💥 Good Answer! {boss.get('name')} is getting hungrier."
            flask_session["enemy_message"] = enemy_message

        else:
            # 4b) Player hunger
            player_hunger += 1
            flask_session["player_current_hunger"] = player_hunger
            flask_session["question_id"] = None
            player_message = "❌ Not good, Squire! You are getting hungrier."
            flask_session["player_message"] = player_message

        # 5) Check victory: boss too hungry
        if boss_hunger >= boss_max_hunger:
            flask_session["boss_defeated"] = True
            xp = boss.get("xp_reward", 0)
            gold = boss.get("gold_reward", 0)
            result.append(update_squire_progress(db, squire_id, xp, gold))

            result.append (
                f"🍕 The {boss.get('name')} is too hungry to continue! "
                f"They run off to eat a pizza.\nYou gain {xp} XP and {gold} bits."
            )

            message = " ".join([str(m) for m in result if m])

            flask_session["combat_result"] = message

            # Clean up combat state
            for key in ("boss", "player_current_hunger", "boss_current_hunger"):
                flask_session.pop(key, None)

            toast = (
                f"{flask_session['squire_name']} defeated {boss.get('name')} "
                f"and gained {xp} XP and {gold} bits."
            )
            add_team_message(flask_session['team_id'], toast)
            db.commit()
            return redirect(url_for("combat_results"))

        # 6) Check defeat: player too hungry
        if player_hunger >= player_max_hunger:
            degrade_gear(squire_id, boss.get("weakness"))
            squire = db.query(Squire).get(squire_id)
            squire.experience_points = max(0, squire.experience_points - 100)
            db.commit()

            flask_session["combat_result"] = (
                "🛑 You are too hungry to continue fighting! "
                "The enemy forces you to flee.\n❌ You lose 100 XP."
            )
            for key in ("boss", "player_current_hunger", "boss_current_hunger"):
                flask_session.pop(key, None)
            return redirect(url_for("combat_results"))

        # 7) Continue boss combat
        return redirect(url_for("boss_combat"))

    finally:
        db.close()

@app.route('/ajax_handle_combat', methods=['POST'])
def ajax_handle_combat():
    """Handles combat via AJAX by updating hunger levels and returning JSON."""
    enemy = flask_session.get("enemy")
    squire_id = flask_session.get("squire_id")
    player_current_hunger = flask_session["player_current_hunger"]
    enemy_current_hunger = flask_session["enemy_current_hunger"]
    player_max_hunger = flask_session["player_max_hunger"]
    mod_enemy_max_hunger = flask_session["mod_enemy_max_hunger"]
    hit_chance = flask_session["hit_chance"]
    mod_for_distance = flask_session["mod_for_distance"]
    flask_session.pop("success",None)
    outcome=[]

    db=db_session()

    if not enemy:
        return jsonify({"redirect": url_for("map_view")})

    # Initialize combat if not already active
    if "combat_active" not in flask_session or not flask_session["combat_active"]:
        flask_session["player_current_hunger"] = 0
        flask_session["enemy_current_hunger"] = 0
        flask_session["battle_log"] = []
        flask_session["combat_active"] = True

    # route based on the button pushed by the user
    action = request.form.get("action")

    if action == "flee":

        if flee_safely(mod_enemy_max_hunger,player_max_hunger, hit_chance) == False:
            flask_session["combat_result"] = "🏃 You managed to escape safely!"
            flask_session["success"] = True
        else:
            degrade_gear(squire_id, enemy["weakness"])
            flask_session["combat_result"] = "🏃 You managed to escape but your armor was damaged during the retreat."
            flask_session["success"] = False
        # Clear session combat variables
        flask_session.pop("enemy", None)
        flask_session.pop("player_current_hunger", None)
        flask_session.pop("enemy_current_hunger", None)
        flask_session.pop("combat_active", None)
        flask_session.pop("battle_log", None)
        flask_session.pop("success",None)
        return jsonify({"redirect": url_for("combat_results")})
    elif action == "question":
        #re-route player to answer a question
        # Clear session combat variables
        flask_session.pop("enemy", None)
        flask_session.pop("player_current_hunger", None)
        flask_session.pop("enemy_current_hunger", None)
        flask_session.pop("combat_active", None)
        flask_session.pop("battle_log", None)
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
        if int(player_current_hunger) >= int(player_max_hunger):
            degrade_gear(squire_id, enemy["weakness"])

            # load the Squire
            squire = db.query(Squire).get(squire_id)
            # subtract XP but never go below zero
            squire.experience_points = max(0, squire.experience_points - enemy["xp_reward"])
            db.commit()

            outcome = f"🛑 You are too hungry to continue fighting! The enemy forces you to flee and damages your gear.\n❌ You lose some XP."
            flask_session["combat_result"] = outcome
            flask_session["success"] = False

            # Clear session variables
            flask_session.pop("enemy", None)
            flask_session.pop("player_current_hunger", None)
            flask_session.pop("enemy_current_hunger", None)
            flask_session.pop("combat_active", None)
            flask_session.pop("battle_log", None)

            return jsonify({"redirect": url_for("combat_results")})

        # result if player won
        if int(enemy_current_hunger) >= int(mod_enemy_max_hunger):
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

            outcome.append(update_squire_progress(squire_id,  xp, bitcoin))
            degrade_gear(squire_id, enemy["weakness"])
            outcome.append(f"🍕 The {enemy['name']} is too hungry to continue! They run off to eat a pizza.\nYou gain {xp} XP and {bitcoin} bits.")

            message = " ".join([str(m) for m in outcome if m])
            flask_session["combat_result"] = message

            # ✅ Reset combat flag and work sessions after combat
            flask_session["forced_combat"] = False
            flask_session["success"] = True
            db.query(Squire) \
              .filter(Squire.id == squire_id) \
              .update({ Squire.work_sessions: 0 }, synchronize_session='fetch')
            db.commit()

            toast = f"{flask_session['squire_name']} defeated {enemy['name']} and gained {xp} XP and {bitcoin} bits."
            add_team_message(flask_session['team_id'],toast)

            # Clear combat session variables
            flask_session.pop("enemy", None)
            flask_session.pop("player_current_hunger", None)
            flask_session.pop("enemy_current_hunger", None)
            flask_session.pop("combat_active", None)
            flask_session.pop("battle_log", None)


            return jsonify({"redirect": url_for("combat_results")})


    # Save updated values in session
    flask_session["player_current_hunger"] = player_current_hunger
    flask_session["enemy_current_hunger"] = enemy_current_hunger
    flask_session["battle_log"] = battle_log

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
        success=flask_session.pop("success", None),
        combat_result=flask_session.pop("combat_result", "")
    )
#Town Routes here

@app.route('/town', methods=['GET'])
def visit_town():
    """Displays the town menu with options to shop, work, or leave."""
    squire_id   = flask_session.get("squire_id")
    job_message = flask_session.get("job_message")

    if not squire_id:
        return redirect(url_for("login"))

    db = db_session()
    try:
        # Fetch the squire’s level via ORM
        squire = db.query(Squire).get(squire_id)
        level  = squire.level
    finally:
        db.close()

    return render_template(
        "town.html",
        level=level,
        job_message=job_message
    )

# 🏪 Shop
@app.route('/shop', methods=['GET'])
def shop():
    """Displays the shop where players can buy items."""
    squire_id = flask_session.get("squire_id")
    if not squire_id:
        return redirect(url_for("login"))

    db = db_session()
    try:
        # 1) Get squire level
        squire = db.query(Squire).get(squire_id)
        level  = squire.level

        # 2) Fetch available shop items
        items = (
            db.query(ShopItem)
              .filter(ShopItem.min_level <= level)
              .all()
        )

        grouped_items = defaultdict(list)
        for item in items:
            grouped_items[item.item_type].append(item)

        # 3) Fetch player's team gold balance
        team = db.query(Team).get(squire.team_id)
        player_gold = team.gold

        # 4) Store in session if needed
        flask_session["player_gold"] = player_gold

    finally:
        db.close()

    return render_template(
        "shop.html",
        grouped_items=grouped_items,
        player_gold=player_gold
    )

@app.route('/buy_item', methods=['POST'])
def buy_item():
    """Handle purchasing an item via ORM instead of raw SQL."""
    data = request.get_json() or {}
    item_id = data.get("item_id")
    squire_id = flask_session.get("squire_id")

    if not item_id or not squire_id:
        return jsonify(success=False, message="Invalid request"), 400

    db = db_session()
    try:
        # 1) Load the shop item
        item = db.query(ShopItem).get(item_id)
        if not item:
            return jsonify(success=False, message="Item not found"), 404

        # 2) Load the squire and their team
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return jsonify(success=False, message="Player not found"), 404

        team = db.query(Team).get(squire.team_id)
        if not team:
            return jsonify(success=False, message="Team not found"), 404

        # 3) Check gold balance
        if team.gold < item.price:
            return jsonify(success=False, message="Not enough gold to buy this item!"), 400

        # 4) Deduct gold and add to inventory
        team.gold -= item.price
        new_inv = Inventory(
            squire_id       = squire_id,
            item_name       = item.item_name,
            description     = item.description,
            uses_remaining  = item.uses,
            item_type       = item.item_type
        )
        db.add(new_inv)
        db.commit()

        # 5) Return updated balance
        return jsonify(
            success=True,
            message=f"You bought {item.item_name}!",
            new_gold=team.gold
        )

    except Exception as e:
        db.rollback()
        return jsonify(success=False, message="Something went wrong!"), 500

    finally:
        db.close()

@app.route('/town_work', methods=['GET', 'POST'])
def town_work():
    """Allows players to take on jobs to earn gold."""
    squire_id = flask_session.get("squire_id")
    level = flask_session.get("level")

    if not squire_id:
        return redirect(url_for("login"))

    MAX_WORK_SESSIONS = 3

    db = db_session()
    try:
        # 1) Load squire
        squire = db.query(Squire).get(squire_id)
        level  = squire.level
        work_sessions = squire.work_sessions

        # 2) Enforce forced combat if too many work sessions
        if flask_session.get("forced_combat"):
            flask_session["job_message"] = (
                "You must face the dangers beyond town before working again!"
            )
            return redirect(url_for("visit_town"))

        if work_sessions >= MAX_WORK_SESSIONS:
            flask_session["forced_combat"] = True
            flask_session["job_message"] = (
                "You must face the dangers beyond town before working again!"
            )
            return redirect(url_for("visit_town"))

        # 3) Handle job selection (POST)
        if request.method == 'POST':
            job_id = request.form.get("job_id", type=int)
            job = db.query(Job).get(job_id)
            if not job:
                flask_session["job_message"] = "❌ Invalid job selection!"
                return redirect(url_for("town_work"))

            payout = random.randint(job.min_payout, job.max_payout) * level
            flask_session["pending_job"] = {
                "job_id":     job.id,
                "job_name":   job.job_name,
                "min_payout": job.min_payout,
                "max_payout": job.max_payout,
                "level":      level
            }

            return redirect(url_for("answer_question"))

        # 4) GET: fetch all jobs
        jobs = db.query(Job).all()

        for job in jobs:
            job.scaled_min = job.min_payout * level
            job.scaled_max = job.max_payout * level

        return render_template(
            "town_work.html",
            jobs=jobs
        )

    finally:
        db.close()

@app.route('/hall_of_fame', methods=['GET'])
def hall_of_fame():
    """Displays the Hall of Fame leaderboard."""
    db = db_session()
    try:
        # Fetch top 10 players by experience_points
        leaders = (
            db.query(Squire)
              .order_by(Squire.experience_points.desc())
              .limit(10)
              .all()
        )
    finally:
        db.close()

    # You can pass ORM objects directly to Jinja:
    # in the template: {{ leader.squire_name }} & {{ leader.experience_points }}
    return render_template("hall_of_fame.html", leaders=leaders)

@app.route('/team_fame', methods=['GET'])
def team_fame():
    """Displays the Hall of Fame leaderboard for Teams Based on Reputation."""
    db = db_session()
    try:
        # Fetch top 10 players by experience_points
        leaders = (
            db.query(Team)
              .order_by(Team.reputation.desc())
              .limit(10)
              .all()
        )
    finally:
        db.close()

    # You can pass ORM objects directly to Jinja:
    # in the template: {{ leader.squire_name }} & {{ leader.experience_points }}
    return render_template("team_hall.html", leaders=leaders)

## riddles and treasure encounters here

@app.route('/riddle_encounter', methods=['GET'])
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

        # 2) Determine which hints to show
        show_hint         = ishint(db, squire_id)
        show_word_length  = iswordlengthhint(db, squire_id)
        show_word_count   = iswordcounthint(db, squire_id)

        # 3) Store current riddle in session for later validation
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

        # 4) Render the riddle page
        return render_template(
            "riddle.html",
            riddle=r,
            show_hint=show_hint,
            show_word_length=show_word_length,
            show_word_count=show_word_count
        )
    except Exception as e:
        logging.error(f"Error in riddle_encounter: {e}")
        return redirect(url_for("map_view"))
    finally:
        db.close()

@app.route('/check_riddle', methods=['POST'])
def check_riddle():
    """Checks if the answer to the riddle is correct, using ORM."""
    squire_id    = flask_session.get("squire_id")
    quest_id     = flask_session.get("quest_id")
    current      = flask_session.get("current_riddle")

    logging.debug(f"Session contents: {flask_session}")
    logging.debug(f"Current riddle in session: {current}")

    if not squire_id or not current:
        logging.error(f"No active riddle found. Squire ID: {squire_id}, Session: {flask_session}")
        return jsonify(success=False, message="❌ No active riddle found!")

    user_answer    = request.form.get("answer", "").strip().lower()
    correct_answer = current["answer"].strip().lower()

    db = db_session()
    try:
        if user_answer == correct_answer:
            riddle_id = current["id"]

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
                sq = SquireQuestion(
                    squire_id=squire_id,
                    question_id=riddle_id,
                    question_type='riddle',
                    answered_correctly=True
                )
                db.add(sq)
            else:
                sq.answered_correctly = True

            db.commit()

            # 3) Calculate and award the special item
            special_item = calculate_riddle_reward(squire_id, riddle_id)

            # 4) Notify the team
            toast = f"{flask_session['squire_name']} solved a riddle and received {special_item}."
            add_team_message(flask_session['team_id'], toast)
            db.commit()

            flask_session.pop("current_riddle", None)
            return jsonify(
                success=True,
                message=f"🎉 Correct! The wizard nods in approval and grants you {special_item}"
            )
        else:
            return jsonify(success=False, message="❌ Incorrect! Try again.")
    except Exception as e:
        db.rollback()
        logging.error(f"Error in check_riddle: {e}")
        return jsonify(success=False, message="❌ An error occurred while checking your answer.")
    finally:
        db.close()

@app.route('/treasure_encounter', methods=['GET'])
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


@app.route('/check_treasure', methods=['POST'])
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
            db.commit()

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
