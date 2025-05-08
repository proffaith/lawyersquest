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

from routes.combat import combat_bp
from routes.map import map_bp
from routes.questions import questions_bp
from routes.town import town_bp

from utils.filters import chance_image


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

from utils.shared import insert_treasure_chests
from utils.shared import generate_terrain_features_dynamic


from utils.shared import get_squire_stats
from utils.shared import check_quest_completion
from utils.shared import complete_quest
from utils.shared import get_random_riddle
from utils.shared import check_riddle_answer
from utils.shared import get_active_quests
from utils.shared import chooseq
from utils.shared import get_riddles_for_quest
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
from utils.shared import calculate_riddle_reward
from utils.shared import ishint
from utils.shared import iswordcounthint
from utils.shared import iswordlengthhint
from utils.shared import get_inventory
from utils.shared import get_viewport_map
from utils.shared import add_team_message

from db import Squire, Course, Team, engine, db_session, Team, TravelHistory, Quest, SquireQuestion, SquireRiddleProgress, Riddle, Enemy, Inventory, WizardItem, Job, MapFeature, MultipleChoiceQuestion, TrueFalseQuestion, ShopItem, SquireQuestStatus, TeamMessage, TreasureChest, XpThreshold, ChestHint

# Load environment variables at the start of the application
load_dotenv()
recaptcha = os.getenv("RECAPTCHA_SECRET_KEY")

app = Flask(__name__)
app.config["DEBUG"] = True
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your_secret_key')  # For session management

app.config["PROPAGATE_EXCEPTIONS"] = True
app.debug = True

app.jinja_env.filters['chance_image'] = chance_image

app.register_blueprint(combat_bp)
app.register_blueprint(map_bp)
app.register_blueprint(questions_bp)
app.register_blueprint(town_bp)

# Database connection function
def get_db_connection():

    try:
        conn = db_session()
        return conn

    except Exception as e:
        logging.error(f"Database connection error: {str(e)}")
        raise



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
    return {"app_version": flask_session.get("ver", "0.3.4")}

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

@app.route("/level_up")
def level_up():
    new_level = flask_session.pop("new_level", None)
    flask_session.pop("leveled_up", None)

    if not new_level:
        return redirect(url_for("map"))  # or map/home if accessed accidentally

    return render_template("level_up.html", level=new_level)


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
                flask_session['ver']         = "0.3.4"

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
    game_message = flask_session.pop('game_message', None)

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
            team_id=team_id,
            game_message=game_message
        )
    except Exception as e:
        logging.error(f"⚠️ Map rendering failed: {str(e)}")
        return jsonify({"error": "Failed to load the map."}), 500

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
