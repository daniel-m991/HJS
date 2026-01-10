"""
Order placement routes for users
"""
from flask import render_template, redirect, url_for, session, flash, request, jsonify
from datetime import datetime


def init_order_routes(app, db, User, Order, PricingConfig):
    
    def require_login():
        """Check if user is logged in"""
        uid = session.get("user_id")
        if not uid:
            return None
        return User.query.get(uid)
    
    @app.post("/order/place")
    def place_order():
        user = require_login()
        if not user:
            return jsonify({"error": "Not logged in"}), 401
        
        coverage_type = request.form.get("coverage_type")  # 'XAN' or 'EXTC'
        duration = request.form.get("duration", type=int)  # hours for XAN, jumps for EXTC
        
        if not coverage_type or not duration:
            return jsonify({"error": "Missing required fields"}), 400
        
        if coverage_type not in ['XAN', 'EXTC']:
            return jsonify({"error": "Invalid coverage type"}), 400
        
        # Check if user already has an active order of the same type
        existing_active = Order.query.filter_by(
            user_id=user.id,
            coverage_type=coverage_type,
            status='active'
        ).first()
        
        if existing_active:
            flash(f"You already have active {coverage_type} insurance coverage.", "info")
            return redirect(url_for("dashboard"))
        
        # Delete any pending order of the same type (replace with new order)
        existing_pending = Order.query.filter_by(
            user_id=user.id,
            coverage_type=coverage_type,
            status='pending'
        ).first()
        
        if existing_pending:
            db.session.delete(existing_pending)
            db.session.commit()  # Commit deletion before creating new order
        
        # Get pricing configuration
        pricing = PricingConfig.query.filter_by(
            coverage_type=coverage_type,
            duration=duration,
            active=True
        ).first()
        
        if not pricing:
            flash("Selected coverage option is not available.", "error")
            return redirect(url_for("dashboard"))
        
        # Create new order
        new_order = Order(
            user_id=user.id,
            coverage_type=coverage_type,
            status='pending',
            xanax_payment=pricing.cost,
            payment_verified=False
        )
        
        if coverage_type == 'XAN':
            new_order.hours = duration
            new_order.xanax_reward = pricing.xanax_reward
        else:  # EXTC
            new_order.jumps = duration
            new_order.xanax_reward = pricing.xanax_reward
            new_order.edvds_reward = pricing.edvds_reward
            new_order.ecstasy_reward = pricing.ecstasy_reward
        
        db.session.add(new_order)
        db.session.commit()
        
        # Flash success message with payment instructions
        message_code = 'HJSx' if coverage_type == 'XAN' else 'HJSe'
        flash(
            f"Order placed! Send {pricing.cost} Xanax to Danieltrsl [2823859] with message: {message_code}",
            "success"
        )
        
        return redirect(url_for("dashboard"))
    
    @app.get("/order/pricing")
    def get_pricing():
        """API endpoint to fetch available pricing options"""
        xan_prices = PricingConfig.query.filter_by(
            coverage_type='XAN',
            active=True
        ).order_by(PricingConfig.duration).all()
        
        extc_prices = PricingConfig.query.filter_by(
            coverage_type='EXTC',
            active=True
        ).order_by(PricingConfig.duration).all()
        
        return jsonify({
            "xan": [
                {
                    "duration": p.duration,
                    "cost": p.cost,
                    "reward": p.xanax_reward
                } for p in xan_prices
            ],
            "extc": [
                {
                    "duration": p.duration,
                    "cost": p.cost,
                    "xanax_reward": p.xanax_reward,
                    "edvds_reward": p.edvds_reward,
                    "ecstasy_reward": p.ecstasy_reward
                } for p in extc_prices
            ]
        })
