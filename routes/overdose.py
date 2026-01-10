"""
Overdose reporting and management routes
"""
from flask import render_template, redirect, url_for, session, flash, request, jsonify
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def init_overdose_routes(app, db, User, Order, Overdose):
    
    @app.get("/overdose")
    def overdose_page():
        uid = session.get("user_id")
        if not uid:
            return redirect(url_for("home"))
        
        user = User.query.get(uid)
        if not user:
            session.clear()
            return redirect(url_for("home"))
        
        # Get active orders for this user
        active_xan = Order.query.filter_by(
            user_id=user.id,
            coverage_type='XAN',
            status='active'
        ).first()
        
        active_extc = Order.query.filter_by(
            user_id=user.id,
            coverage_type='EXTC',
            status='active'
        ).first()
        
        # Get recent overdoses (all users for display)
        recent_overdoses = Overdose.query.order_by(Overdose.reported_at.desc()).limit(20).all()
        
        return render_template(
            "overdose.html",
            user=user,
            active_xan=active_xan,
            active_extc=active_extc,
            recent_overdoses=recent_overdoses
        )
    
    @app.post("/overdose/report")
    def report_overdose():
        uid = session.get("user_id")
        if not uid:
            return jsonify({"error": "Not logged in"}), 401
        
        user = User.query.get(uid)
        if not user:
            session.clear()
            return jsonify({"error": "User not found"}), 404
        
        # Check for active coverage
        active_xan = Order.query.filter_by(
            user_id=user.id,
            coverage_type='XAN',
            status='active'
        ).first()
        
        active_extc = Order.query.filter_by(
            user_id=user.id,
            coverage_type='EXTC',
            status='active'
        ).first()
        
        # Must have at least one active coverage
        if not active_xan and not active_extc:
            return jsonify({"error": "No active coverage. Cannot report overdose."}), 400
        
        # If both are active, user must specify which one
        coverage_type = request.json.get("coverage_type") if request.is_json else None
        if active_xan and active_extc and not coverage_type:
            return jsonify({
                "error": "Multiple active coverages detected. Please choose.",
                "has_xan": True,
                "has_extc": True
            }), 400
        
        # Default to available coverage if only one active
        if not coverage_type:
            coverage_type = 'XAN' if active_xan else 'EXTC'
        
        # Validate selected coverage exists
        if coverage_type == 'XAN' and not active_xan:
            return jsonify({"error": "No active Xanax coverage"}), 400
        if coverage_type == 'EXTC' and not active_extc:
            return jsonify({"error": "No active Ecstasy coverage"}), 400
        
        # Check reporting limits
        if coverage_type == 'EXTC':
            # EXTC: Can report once per active order (not limited to 1 lifetime)
            # Check if user has already reported an overdose for the current active EXTC order
            current_extc_order = Order.query.filter_by(
                user_id=user.id,
                coverage_type='EXTC',
                status='active'
            ).first()
            
            if current_extc_order:
                # Check if there's already a confirmed overdose for this specific order
                existing_extc = Overdose.query.filter_by(
                    user_id=user.id,
                    coverage_type='EXTC',
                    confirmed=True
                ).filter(Overdose.confirmed_at >= current_extc_order.activated_at).first()
                
                if existing_extc:
                    return jsonify({"error": "You have already reported an Ecstasy overdose for this order."}), 400
        
        elif coverage_type == 'XAN':
            # XAN: Only 1 report per 4 hours
            four_hours_ago = datetime.utcnow() - timedelta(hours=4)
            recent_xan = Overdose.query.filter_by(
                user_id=user.id,
                coverage_type='XAN',
                confirmed=True
            ).filter(Overdose.confirmed_at > four_hours_ago).first()
            if recent_xan:
                time_diff = recent_xan.confirmed_at + timedelta(hours=4) - datetime.utcnow()
                hours_remaining = time_diff.total_seconds() / 3600
                return jsonify({
                    "error": f"You can only report Xanax overdose once per 4 hours. Next available in {hours_remaining:.1f} hours."
                }), 400
        
        # Create overdose report with coverage type
        overdose = Overdose(
            user_id=user.id,
            coverage_type=coverage_type,
            reported_at=datetime.utcnow()
        )
        
        db.session.add(overdose)
        db.session.commit()
        
        flash(f"Overdose reported for {coverage_type}!", "success")
        return jsonify({"success": True, "overdose_id": overdose.id}), 201
    
    @app.post("/admin/overdose/confirm")
    def confirm_overdose():
        # Check admin access
        uid = session.get("user_id")
        if not uid:
            return jsonify({"error": "Not logged in"}), 401
        
        admin = User.query.get(uid)
        if not admin or admin.role_id != 3:
            return jsonify({"error": "Admin access required"}), 403
        
        # Get overdose ID and notes from request
        data = request.get_json()
        overdose_id = data.get("overdose_id")
        notes = data.get("notes", "")
        
        if not overdose_id:
            return jsonify({"error": "Overdose ID required"}), 400
        
        overdose = Overdose.query.get(overdose_id)
        if not overdose:
            return jsonify({"error": "Overdose not found"}), 404
        
        # Get the active order for this user and coverage type to determine payout
        active_order = Order.query.filter_by(
            user_id=overdose.user_id,
            coverage_type=overdose.coverage_type,
            status='active'
        ).first()
        
        if not active_order:
            return jsonify({"error": f"No active {overdose.coverage_type} cover found for this user"}), 400
        
        # Build payout details
        if overdose.coverage_type == 'XAN':
            payout_details = f"{active_order.xanax_reward} Xanax"
            payout = active_order.xanax_reward
        else:  # EXTC
            payout_details = f"{active_order.xanax_reward} Xanax, {active_order.edvds_reward} eDVDs, {active_order.ecstasy_reward} Ecstasy"
            payout = active_order.xanax_reward  # Store primary payout
        
        # Update overdose
        overdose.confirmed = True
        overdose.confirmed_at = datetime.utcnow()
        overdose.payout = payout
        overdose.payout_details = payout_details
        overdose.notes = notes
        
        # Store individual payout amounts
        overdose.payout_xanax = active_order.xanax_reward
        if overdose.coverage_type == 'EXTC':
            overdose.payout_edvds = active_order.edvds_reward
            overdose.payout_ecstasy = active_order.ecstasy_reward
        
        # Move EXTC order to expired so user can place a new one
        if overdose.coverage_type == 'EXTC':
            active_order.status = 'expired'
        
        db.session.commit()
        
        flash(f"Overdose confirmed with payout: {payout_details}", "success")
        return jsonify({"success": True, "payout": payout_details}), 200
    
    @app.delete("/admin/overdose/<int:overdose_id>")
    def delete_overdose(overdose_id):
        # Check admin access
        uid = session.get("user_id")
        if not uid:
            return jsonify({"error": "Not logged in"}), 401
        
        admin = User.query.get(uid)
        if not admin or admin.role_id != 3:
            return jsonify({"error": "Admin access required"}), 403
        
        overdose = Overdose.query.get(overdose_id)
        if not overdose:
            return jsonify({"error": "Overdose not found"}), 404
        
        db.session.delete(overdose)
        db.session.commit()
        
        return jsonify({"success": True}), 200
    
    @app.get("/admin/overdose/check-limits")
    def check_overdose_limits():
        """Check if user can report overdose based on coverage type limits"""
        uid = session.get("user_id")
        if not uid:
            return jsonify({"error": "Not logged in"}), 401
        
        user = User.query.get(uid)
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        # Check EXTC limit (1 per active order)
        current_extc_order = Order.query.filter_by(
            user_id=user.id,
            coverage_type='EXTC',
            status='active'
        ).first()
        
        extc_limit_hit = False
        if current_extc_order:
            # Check if there's already a confirmed overdose for this specific order
            existing_extc = Overdose.query.filter_by(
                user_id=user.id,
                coverage_type='EXTC',
                confirmed=True
            ).filter(Overdose.confirmed_at >= current_extc_order.activated_at).first()
            extc_limit_hit = existing_extc is not None
        
        # Check XAN limit (1 per 4 hours)
        four_hours_ago = datetime.utcnow() - timedelta(hours=4)
        recent_xan = Overdose.query.filter_by(
            user_id=user.id,
            coverage_type='XAN',
            confirmed=True
        ).filter(Overdose.confirmed_at > four_hours_ago).first()
        
        xan_limit_hit = recent_xan is not None
        hours_until_next_xan = 0.0
        if xan_limit_hit:
            time_diff = recent_xan.confirmed_at + timedelta(hours=4) - datetime.utcnow()
            hours_until_next_xan = max(0, time_diff.total_seconds() / 3600)
        
        return jsonify({
            "can_report_xan": not xan_limit_hit,
            "can_report_extc": not extc_limit_hit,
            "hours_until_next_xan": hours_until_next_xan
        }), 200
