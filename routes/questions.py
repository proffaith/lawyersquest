# Question-related routes
from flask import Blueprint, session as flask_session, request, jsonify, render_template, redirect, url_for, flash
from db import db_session, Squire, TrueFalseQuestion, SquireQuestion, MultipleChoiceQuestion, Team, SquireTournamentScore, SquireQuestionAttempt
from sqlalchemy import func, and_, desc
import random
import logging
import uuid

from utils.shared import add_team_message
from utils.shared import degrade_gear
from utils.shared import complete_quest
from utils.shared import check_quest_completion
from utils.shared import update_squire_question_attempt
from utils.shared import update_squire_question

from utils.api_calls import generate_openai_question
from services.progress import update_squire_progress

questions_bp = Blueprint('questions', __name__)



@questions_bp.route('/npc_encounter/<int:quest_id>', methods=['GET'])
def npc_encounter(quest_id):
    excerpt = get_random_excerpt_from_textbook(quest_id)

    if should_use_api():
        question = generate_openai_question(excerpt)
        source = "openai"
    else:
        question = get_question_from_db(quest_id)
        source = "db"

    return render_template("npc_encounter.html", question=question, source=source)


@questions_bp.route('/handle_true_false_question', methods=['POST'])
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

                new_attempt = SquireQuestionAttempt(
                    squire_id=squire_id,
                    question_id=0,
                    question_type='true_false',  # must match one of the ENUM values
                    answered_correctly=False,
                    quest_id=quest_id
                    )
                try:
                    session.add(new_attempt)
                    db.commit()
                except Exception as e:
                    logging.error(f"Error committing response to T/F question {e}")

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
            new_attempt = SquireQuestionAttempt(
                squire_id=squire_id,
                question_id=tq.id,
                question_type='true_false',  # must match one of the ENUM values
                answered_correctly=True
                )

            try:
                session.add(new_attempt)
                add_team_message(flask_session['team_id'], toast)
                db.commit()

            except Exception as e:
                logging.error(f"Error committing response to T/F question {e}")


            return jsonify(
                success=True,
                message=win_msg,
                xp_reward=xp_gain,
                gold_reward=gold_gain,
                defeated=True,
                leveled_up=flask_session.get("leveled_up", False)
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

        new_attempt = SquireQuestionAttempt(
            squire_id=squire_id,
            question_id=tq.id,
            question_type='true_false',  # must match one of the ENUM values
            answered_correctly=True,
            quest_id=quest_id
            )

        try:
            session.add(new_attempt)
            db.commit()
        except Exception as e:
            logging.error(f"Error committing response to T/F question {e}")

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

@questions_bp.route('/answer_question', methods=['GET'])
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
            question_type = random.choice(["true_false", "multiple_choice", "api_question"])
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
                return redirect(url_for("combat.combat"))

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

    elif question_type == "api_question":

        try:
            q_data = generate_openai_question(quest_id)

            # Save it in session for validation
            flask_session["current_question"] = {
                "id": "api",  # No DB ID
                "type": "api_generated",
                "text": q_data["question"],
                "options": q_data["options"],
                "correct_answer": q_data["correct_answer"]
            }

            return render_template("answer_question_mc.html", question=flask_session["current_question"])
        except Exception as e:
            flask_session["battle_summary"] = f"OpenAI Error: {e}"
            return redirect(url_for("ajax_handle_combat"))

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
            return redirect(url_for("combat.combat"))

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

@questions_bp.route('/check_true_false_question', methods=['POST'])
def check_true_false_question():
    """Validates the player's True/False answer."""
    squire_id    = flask_session.get("squire_id")
    question_id  = request.form.get("question_id")
    source = request.form.get("source")

    quest_id  = flask_session.get("quest_id")
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
        # 1) Load question and immediately capture all needed data
        q = db.query(TrueFalseQuestion).get(int(question_id))
        if not q:
            flask_session["battle_summary"] = "Error: Question not found."
            return redirect(url_for("combat_results"))

        # CAPTURE ALL DATA IMMEDIATELY to avoid detached instance errors
        question_id_int = int(question_id)
        correct_answer = q.correct_answer  # Store the boolean value
        correct_int = 1 if correct_answer else 0
        hint_text = q.hint or ""  # Store the hint text
        question_db_id = q.id  # Store the database ID

        user_int = 1 if user_answer == "T" else 0

        logging.debug(f"TF Check: squire={squire_id}, qid={question_id}, "
                      f"user={user_int}, correct={correct_int}")

        # 2) Record as answered correctly if matches
        if user_int == correct_int:

            new_attempt = update_squire_question_attempt(db, squire_id, question_db_id, 'true_false', True, quest_id)
            sq = (
                db.query(SquireQuestion)
                  .filter_by(
                      squire_id=squire_id,
                      question_id=question_db_id,
                      question_type='true_false'
                  )
                  .one_or_none()
            )

            if not sq:
                new_question = update_squire_question(db, squire_id, question_id_int, 'true_false', True)
            else:
                sq.answered_correctly = True

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

                try:
                    db.commit()
                except Exception as e:
                    logging.error(f"Error committing response to T/F question {e}")

                msg = (f"✅ You completed '{pending_job['job_name']}' "
                       f"and earned 💰 {payout} bits!")
                flask_session["job_message"] = msg

                toast.append (f"{flask_session['squire_name']} completed "
                         f"'{pending_job['job_name']}' and earned 💰 {payout} bits.")
                add_team_message(squire.team_id, toast)

                return redirect(url_for("town.visit_town"))

            # 3b) Combat reward
            flask_session["forced_combat"] = False
            if source == "dungeon":
                xp_gain = 10
                gold_gain = 10
            else:
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
            try:
                db.commit()
            except Exception as e:
                logging.error(f"Error committing team message for T/F question {e}")

            flask_session["combat_result"] = (
                f"✅ Correct! You have defeated the enemy "
                f"and earned {xp_gain} XP and {gold_gain} bits."
            )
            flask_session["success"] = True
            if flask_session.get("leveled_up"):
                return redirect(url_for("level_up"))

        else:
            # 4) Incorrect answer handling - use captured hint_text
            if pending_job:
                flask_session["job_message"] = (
                    f"❌ Incorrect! You failed the task and earned nothing but this hint: {hint_text}."
                )
                return redirect(url_for("town.visit_town"))

            # Damage gear and penalize XP
            degrade_gear(squire_id, enemy.get("weakness"))
            squire = db.query(Squire).get(squire_id)

            if source == "dungeon":
                squire.experience_points = squire.experience_points - 10
            else:
                squire.experience_points = max(0, squire.experience_points - enemy.get("xp_reward", 0))

            try:
                db.commit()
            except Exception as e:
                logging.error(f"Error committing for T/F question {e}")

            new_attempt = update_squire_question_attempt(db, squire_id, question_db_id, 'true_false', False, quest_id)

            base_message = (
                f"❌ Incorrect! You are defeated by {enemy.get('name')} and lose some experience points!\n"
                if enemy
                else "❌ Wrong answer: you lose some experience points!\n"
            )
            # Use the captured hint_text directly
            full_message = base_message + (hint_text if hint_text else "")
            flask_session["combat_result"] = full_message
            flask_session["success"] = False

        # 5) Show results
        if source == "dungeon":
            return redirect(url_for("dungeon.dungeon_map"))

        return render_template(
            "combat_results.html",
            success=flask_session.pop("success", None),
            combat_result=flask_session.pop("combat_result", "")
        )

    except Exception as e:
        logging.error(f"General error in check_true_false_question: {e}")
        flask_session["battle_summary"] = f"Error: {e}."
        return render_template(
            "combat_results.html",
            success=flask_session.pop("success", None),
            combat_result=flask_session.pop("combat_result", "")
        )

    finally:
        db.close()

@questions_bp.route('/check_MC_question_enemy', methods=['POST'])
def check_MC_question_enemy():
    """Validates the player's True/False answer."""
    squire_id    = flask_session.get("squire_id")
    quest_id = flask_session.get("quest_id")
    source = request.form.get("source")
    enemy        = flask_session.get("enemy", {})
    pending_job  = flask_session.pop("pending_job", None)
    user_answer  = request.form.get("answer", "").strip().upper()
    question_id  = request.form.get("question_id")

    flask_session.pop("success", None)

    db = db_session()

    logging.debug(f"Check_MC_question qid/user_answer {question_id}/{user_answer}")

    if not (squire_id and question_id):
        flask_session["battle_summary"] = "Error: Missing session or question."
        return redirect(url_for("combat.combat_results"))

    if question_id == "api":
        try:
            toast =[]

            current_q = flask_session.get("current_question")
            if not current_q:
                flask_session["combat_result"] = "Error: Question not found in session."
                return redirect(url_for("combat.combat_results"))

            correct = (user_answer == current_q["correct_answer"])

            if correct:
                new_attempt = update_squire_question_attempt(db, squire_id, -1, 'api_generated', True, quest_id)
                new_question = update_squire_question(db, squire_id, -int(uuid.uuid4().int % 1000000000), 'api_generated', True)

                team = db.query(Team).get(flask_session['team_id'])
                team.reputation += 1

                try:
                    db.commit()
                except Exception as e:
                    logging.error(f"Error committing team message for API M/C question {e}")

                # 3b) Combat reward
                flask_session["forced_combat"] = False

                if source == "dungeon":
                    xp_gain = 25
                    gold_gain = 25
                else:
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
                # Damage gear and penalize XP
                degrade_gear(squire_id, enemy.get("weakness"))
                new_attempt = update_squire_question_attempt(db, squire_id, -1, 'api_generated', False, quest_id)

                squire = db.query(Squire).get(squire_id)
                if source == "dungeon":
                    squire.experience_points = squire.experience_points - 25
                else:
                    squire.experience_points = max(0, squire.experience_points - enemy.get("xp_reward", 0))

                try:
                    db.commit()
                except Exception as e:
                    logging.error(f"Error committing  for M/C question {e}")

                base_message = (
                    f"❌ Incorrect! You are defeated by {enemy.get('name')} and lose some experience points!\n"
                    if enemy
                    else "❌ Wrong answer: you lose some experience points!\n"
                )
                hint_text = f"{hint}" if hint else ""
                flask_session["combat_result"] = base_message + hint_text
                flask_session["success"] = False

            return render_template(
                "combat_results.html",
                success=flask_session.pop("success", None),
                combat_result=flask_session.pop("combat_result", ""))
        except Exception as e:
            logging.error(f"There was a problem with the API MC submission: {e}")
        finally:
            db.close()


    toast =[]

    try:
        # 1) Load the MC question
        mcq = db.query(MultipleChoiceQuestion).get(question_id)
        if not mcq:
            flask_session["battle_summary"] = "Error: Question not found."
            return redirect(url_for("combat.combat_results"))

        # 2) Determine correctness
        correct = (user_answer == mcq.correctAnswer)

        # 3) Record attempt if correct
        if correct:
            new_attempt = update_squire_question_attempt(db, squire_id,mcq.id, 'multiple_choice', True, quest_id)

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
                new_question = update_squire_question(db, squire_id, -int(uuid.uuid4().int % 1000000000), 'multiple_choice', True)
            else:
                sq.answered_correctly = True

            try:
                db.commit()
            except Exception as e:
                logging.error(f"Error committing  for M/C question {e}")


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

                try:
                    db.commit()
                except Exception as e:
                    logging.error(f"Error committing team update M/C question {e}")

                msg = (f"✅ You completed '{pending_job['job_name']}' "
                       f"and earned 💰 {payout} bits!")
                flask_session["job_message"] = msg

                toast.append (f"{flask_session['squire_name']} completed "
                         f"'{pending_job['job_name']}' and earned 💰 {payout} bits.")
                add_team_message(squire.team_id, toast)

                return redirect(url_for("town.visit_town"))

            # 3b) Combat reward
            flask_session["forced_combat"] = False

            if source == "dungeon":
                xp_gain = 25
                gold_gain = 25
            else:
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

            try:
                db.commit()
            except Exception as e:
                logging.error(f"Error committing team message for M/C question {e}")

            flask_session["combat_result"] = (
                f"✅ Correct! You have defeated the enemy "
                f"and earned {xp_gain} XP and {gold_gain} bits."
            )
            flask_session["success"] = True

            if source == "dungeon":
                return redirect(url_for("dungeon.dungeon_map"))

            return redirect(url_for("combat.combat_results"))

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
                return redirect(url_for("town.visit_town"))

            new_attempt = update_squire_question_attempt(db, squire_id,mcq.id, 'multiple_choice', False, quest_id)

            # Damage gear and penalize XP
            degrade_gear(squire_id, enemy.get("weakness"))

            squire = db.query(Squire).get(squire_id)

            if source == "dungeon":
                squire.experience_points = squire.experience_points - 25
            else:
                squire.experience_points = max(0, squire.experience_points - enemy.get("xp_reward", 0))

            try:
                db.commit()
            except Exception as e:
                logging.error(f"Error committing  for M/C question {e}")

            base_message = (
                f"❌ Incorrect! You are defeated by {enemy.get('name')} and lose some experience points!\n"
                if enemy
                else "❌ Wrong answer: you lose some experience points!\n"
            )
            hint_text = f"{hint}" if hint else ""
            flask_session["combat_result"] = base_message + hint_text
            flask_session["success"] = False

        if source == "dungeon":
            return redirect(url_for("dungeon.dungeon_map"))

        return render_template(
            "combat_results.html",
            success=flask_session.pop("success", None),
            combat_result=flask_session.pop("combat_result", ""))

    finally:
        db.close()

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Boss and Tourney Section
@questions_bp.route('/answer_MC_question', methods=['GET'])
def answer_MC_question():
    """Displays a random multiple‐choice question for boss combat."""
    boss       = flask_session.get('boss', None)
    squire_id  = flask_session.get("squire_id")
    quest_id   = flask_session.get("quest_id")

    if not (squire_id and quest_id):
        return redirect(url_for("login"))

    # set mode
    if quest_id == 14:
        flask_session['mode'] = 'combat'
    elif quest_id in (28, 32):
        # start tournament mode if not already started
        flask_session['mode'] = 'tournament'
        if 'tournament_score' not in flask_session:
            flask_session['tournament_score'] = 0


    # pull in hunger if needed elsewhere
    player_current_hunger = flask_session.get("player_current_hunger", None)
    boss_current_hunger   = flask_session.get("boss_current_hunger", None)


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
        mode = flask_session.get("mode")

        # 2) Fetch a random MCQ with quest_id < current and not yet seen

        if  mode == "tournament" and quest_id == 28:
            mcq = (
                db.query(MultipleChoiceQuestion)
                    .filter(
                        MultipleChoiceQuestion.quest_id.in_([23, 24, 25, 26, 27]),
                        ~MultipleChoiceQuestion.id.in_(answered_ids)
                        )
                        .order_by(func.rand())
                        .first()
                    )
        elif mode == "combat" and quest_id == 14:
            mcq = (
                db.query(MultipleChoiceQuestion)
                    .filter(
                        MultipleChoiceQuestion.quest_id.in_([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13]),
                        ~MultipleChoiceQuestion.id.in_(answered_ids)
                        )
                        .order_by(func.rand())
                        .first()
                    )
        elif mode == "tournament" and quest_id == 32:
            mcq = (
                db.query(MultipleChoiceQuestion)
                    .filter(
                        MultipleChoiceQuestion.quest_id.in_([15, 16, 17, 18, 19, 20, 21, 22, 29, 30, 31]),
                        ~MultipleChoiceQuestion.id.in_(answered_ids)
                        )
                        .order_by(func.rand())
                        .first()
                    )
        else:
            mcq = ( db.query(MultipleChoiceQuestion)
            .filter(MultipleChoiceQuestion.quest_id < quest_id,
            ~MultipleChoiceQuestion.id.in_(answered_ids))
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

        if flask_session.get("mode") == "tournament":
            return render_template('tourney_combat.html')

        else:
            return render_template(
                'boss_combat.html',
                boss=boss,
                enemy_message=flask_session.pop("enemy_message", ""),
                player_message=flask_session.pop("player_message", "")
            )


    finally:
        db.close()


#then need a route to check if the question was answered correctly so that that can be recorded as either
#increasing the player's hunger or the enemy's hunger
@questions_bp.route('/check_MC_question', methods=['POST'])
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
    quest_id           = flask_session.get("quest_id")
    result = []

    mode = flask_session.get("mode")
    score = flask_session.get("tournament_score", 0)
    next_route = 'questions.answer_MC_question'
    won = False
    lost = False

    logging.debug(f"Check_MC_question qid/user_answer {question_id}/{user_answer}")
    db = db_session()
    try:
        # 1) Load the MC question
        mcq = db.query(MultipleChoiceQuestion).get(question_id)
        if not mcq:
            flask_session["battle_summary"] = "Error: Question not found."
            return redirect(url_for("combat.combat_results"))

        # 2) Determine correctness
        correct = (user_answer == mcq.correctAnswer)

        if mode == "tournament":
            if correct:
                score += 1
                flask_session["tournament_score"] = score

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ db functions
                new_attempt = SquireQuestionAttempt(
                    squire_id=squire_id,
                    question_id=mcq.id,
                    question_type='multiple_choice',  # must match one of the ENUM values
                    answered_correctly=True,
                    quest_id=quest_id
                    )
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

                try:
                    db.add(new_attempt)
                    db.commit()
                except Exception as e:
                    logging.error(f"Error committing team message for M/C question {e}")
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ db functions

                next_route = 'questions.answer_MC_question'

            else: #incorrect tourney ends the run
                flask_session.pop("mode", None)
                next_route = 'questions.tourney_results'

        else:
            #boss combat
            if correct:

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ db functions
                new_attempt = SquireQuestionAttempt(
                    squire_id=squire_id,
                    question_id=mcq.id,
                    question_type='multiple_choice',  # must match one of the ENUM values
                    answered_correctly=True,
                    quest_id=quest_id
                    )
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

                try:
                    db.add(new_attempt)
                    db.commit()
                except Exception as e:
                    logging.error(f"Error committing team message for M/C question {e}")
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ db functions

                boss_hunger += 1
                flask_session["boss_current_hunger"] = boss_hunger
                flask_session["question_id"] = None
                enemy_message = f"💥 Good Answer! {boss.get('name')} is getting hungrier."
                flask_session["enemy_message"] = enemy_message

                next_route = 'questions.answer_MC_question'

            else:
                # 4b) Player hunger
                player_hunger += 1
                flask_session["player_current_hunger"] = player_hunger
                flask_session["question_id"] = None
                player_message = "❌ Not good, Squire! You are getting hungrier."
                flask_session["player_message"] = player_message

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ db functions

                new_attempt = SquireQuestionAttempt(
                    squire_id=squire_id,
                    question_id=mcq.id,
                    question_type='multiple_choice',  # must match one of the ENUM values
                    answered_correctly=False,
                    quest_id=quest_id
                    )

                try:
                    db.add(new_attempt)
                    db.commit()
                except Exception as e:
                    logging.error(f"Error committing team message for M/C question {e}")

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ db functions

                next_route = 'questions.answer_MC_question'

            if boss_hunger >= boss_max_hunger:
                flask_session["boss_defeated"] = True
                xp = boss.get("xp_reward", 0)
                gold = boss.get("gold_reward", 0)
                result = []

                update_squire_progress(squire_id, xp, gold)
                result.append(
                    f"🍕 The {boss.get('name')} is too hungry to continue! "
                    f"They run off to eat a pizza.\nYou gain {xp} XP and {gold} bits."
                )

                flask_session["combat_result"] = " ".join(result)

                # Clean up combat state
                for key in ("boss", "player_current_hunger", "boss_current_hunger"):
                    flask_session.pop(key, None)

                toast = (
                    f"{flask_session['squire_name']} defeated {boss.get('name')} "
                    f"and gained {xp} XP and {gold} bits."
                )
                try:
                    add_team_message(flask_session['team_id'], toast)
                    db.commit()
                except Exception as e:
                    logging.error(f"Error committing team message for M/C question {e}")

                flask_session["quest_completed"] = True
                completed, messages = complete_quest(squire_id, quest_id)
                if completed:
                    for msg in messages:
                        flash(msg, "success")
                    return redirect(url_for("quest_select"))  # ✅ RETURN IMMEDIATELY

                # Otherwise fall through to combat results
                return redirect(url_for("combat.combat_results"))  # ✅ Don't let it fall past this point


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

                lost = True

        if won or lost:
            return redirect(url_for("combat.combat_results"))
        else:
            return redirect(url_for(next_route))


    except Exception as e:
        logging.error(f"Boss/Tourney Combat error {e}")
        return redirect(url_for("map_view"))

    finally:
        db.close()


@questions_bp.route('/tourney_results')
def tourney_results():
    squire_id = flask_session.get('squire_id')
    team_id   = flask_session.get('team_id')
    quest_id  = flask_session.get('quest_id')
    score     = flask_session.pop('tournament_score', 0)
    flask_session.pop('mode', None)

    db = db_session()
    try:
        # 1) Save the run
        tr = SquireTournamentScore(
            squire_id=squire_id,
            quest_id=quest_id,
            score=score
        )
        db.add(tr)
        db.commit()

        # 2) Mark the quest complete (award XP/gold or just flag it)
        #    You’ve used update_squire_progress elsewhere:
        update_squire_progress(squire_id, 500, 500)
        complete_quest(squire_id, quest_id)
        db.commit()

        # 2) Build the full leaderboard: all individual runs, by team
        leaderboard = (
            db.query(
                Team.team_name.label('team_name'),
                Squire.squire_name.label('squire_name'),
                SquireTournamentScore.score,
                SquireTournamentScore.timestamp
            )
            .join(Squire, SquireTournamentScore.squire_id == Squire.id)
            .join(Team,   Squire.team_id   == Team.id)
            .filter(SquireTournamentScore.quest_id == quest_id)
            .order_by(
                Team.team_name,                       # alphabetical by team
                desc(SquireTournamentScore.score)     # highest scores first
            )
            .all()
        )
    finally:
        db.close()

    return render_template(
        'tourney_results.html',
        leaderboard=leaderboard,
        your_score=score
    )


#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ End Boss/Tourney
