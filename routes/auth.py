import requests
from flask import request, redirect, url_for, session, flash


def init_auth_routes(app, db, User, fetch_torn_basic, admin_torn_id, mod_torn_ids):
    @app.post("/login")
    def login():
        api_key = (request.form.get("api_key") or "").strip()

        try:
            basic = fetch_torn_basic(api_key)
            torn_user_id = int(basic.get("player_id"))
            torn_name = str(basic.get("name") or "").strip()

            if not torn_user_id or not torn_name:
                raise ValueError("Could not read user id/name from Torn response.")

            if torn_user_id == admin_torn_id:
                role_id = 3
            elif torn_user_id in mod_torn_ids:
                role_id = 2
            else:
                role_id = 1

        except requests.RequestException:
            flash("Network/API problem talking to Torn. Try again in a moment.", "error")
            return redirect(url_for("home"))
        except ValueError as e:
            flash(f"Login failed: {e}", "error")
            return redirect(url_for("home"))
        except Exception:
            flash("Login failed due to an unexpected error.", "error")
            return redirect(url_for("home"))

        user = User.query.filter_by(torn_user_id=torn_user_id).first()
        if user is None:
            user = User(
                torn_user_id=torn_user_id,
                torn_name=torn_name,
                role_id=role_id,
                sent_xanax_total=0,
                insurance_total=0,
            )
            db.session.add(user)
        else:
            user.torn_name = torn_name
            user.role_id = role_id

        db.session.commit()

        session.clear()
        session["user_id"] = user.id
        session.permanent = True

        flash(f"Logged in as {user.torn_name} [{user.torn_user_id}].", "success")
        return redirect(url_for("dashboard"))

    @app.post("/logout")
    def logout():
        session.clear()
        flash("Logged out.", "success")
        return redirect(url_for("home"))
