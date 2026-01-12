"""
Admin routes for order management and verification
"""
from flask import render_template, redirect, url_for, session, flash, request, jsonify
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.order_verification import verify_order_payment, auto_detect_new_orders


def init_admin_routes(app, db, User, Order, PricingConfig, AutoVerifySettings, Overdose=None):
    
    def require_admin():
        """Check if current user is admin"""
        uid = session.get("user_id")
        if not uid:
            return None
        user = User.query.get(uid)
        if not user or user.role_id != 3:
            return None
        return user
    
    @app.post("/admin/set-api-key")
    def set_admin_api_key():
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Unauthorized"}), 403
        
        data = request.get_json()
        api_key = data.get("api_key", "").strip()
        
        if not api_key or len(api_key) < 8:
            return jsonify({"error": "Invalid API key"}), 400
        
        admin.api_key = api_key
        db.session.commit()
        
        flash("Admin API key set successfully!", "success")
        return jsonify({"success": True}), 200
    
    @app.get("/admin")
    def admin_panel():
        admin = require_admin()
        if not admin:
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for("home"))
        
        # Get statistics
        pending_orders = Order.query.filter_by(status='pending').all()
        active_orders = Order.query.filter_by(status='active').all()
        
        # Get auto-verify settings
        auto_settings = AutoVerifySettings.query.first()
        if not auto_settings:
            auto_settings = AutoVerifySettings(enabled=False, interval_minutes=5)
            db.session.add(auto_settings)
            db.session.commit()
        
        # Get pricing configs
        xan_prices = PricingConfig.query.filter_by(coverage_type='XAN', active=True).order_by(PricingConfig.duration).all()
        extc_prices = PricingConfig.query.filter_by(coverage_type='EXTC', active=True).order_by(PricingConfig.duration).all()
        
        # Get pending overdoses only (not confirmed)
        pending_overdoses = []
        if Overdose:
            pending_overdoses = Overdose.query.filter_by(confirmed=False).order_by(Overdose.reported_at.desc()).limit(20).all()
        
        return render_template("admin.html",
                             user=admin,
                             pending_orders=pending_orders,
                             active_orders=active_orders,
                             auto_settings=auto_settings,
                             xan_prices=xan_prices,
                             extc_prices=extc_prices,
                             recent_overdoses=pending_overdoses)
    
    @app.get("/admin/orders/pending-to-verify")
    def get_pending_orders_to_verify():
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Unauthorized"}), 403
        
        # Auto-detect pending orders needing verification
        pending_orders = Order.query.filter_by(status='pending', payment_verified=False).all()
        
        orders_data = []
        for order in pending_orders:
            orders_data.append({
                "id": order.id,
                "user_name": order.user.torn_name,
                "user_id": order.user.torn_user_id,
                "coverage_type": order.coverage_type,
                "duration": order.hours if order.coverage_type == 'XAN' else order.jumps,
                "duration_unit": "H" if order.coverage_type == 'XAN' else "J",
                "payment": order.xanax_payment,
                "created_at": order.created_at.isoformat()
            })
        
        return jsonify({
            "count": len(orders_data),
            "orders": orders_data
        }), 200
    
    @app.get("/admin/pending-orders-list")
    def get_pending_orders_list():
        try:
            admin = require_admin()
            if not admin:
                return jsonify({"error": "Unauthorized"}), 403
            
            # Get all pending orders for dropdown
            pending_orders = Order.query.filter_by(status='pending').all()
            
            orders_data = []
            for order in pending_orders:
                orders_data.append({
                    "id": order.id,
                    "user_db_id": order.user_id,  # Database user ID for activation
                    "user_name": order.user.torn_name,
                    "user_torn_id": order.user.torn_user_id,  # Torn API ID for display
                    "coverage_type": order.coverage_type,
                    "duration": order.hours if order.coverage_type == 'XAN' else order.jumps,
                    "duration_unit": "H" if order.coverage_type == 'XAN' else "J",
                    "payment": order.xanax_payment
                })
            
            return jsonify({"orders": orders_data}), 200
        except Exception as e:
            app.logger.exception("Error in get_pending_orders_list")
            return jsonify({"error": str(e), "orders": []}), 500
    
    @app.post("/admin/verify-orders-confirm")
    def verify_orders_confirm():
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Unauthorized"}), 403
        
        if not admin.api_key:
            return jsonify({"error": "Admin API key not configured"}), 400
        
        # Get all pending orders
        pending_orders = Order.query.filter_by(status='pending', payment_verified=False).all()
        
        verified_count = 0
        failed_count = 0
        
        for order in pending_orders:
            try:
                verified, payment_time, event = verify_order_payment(order, admin.api_key)
                
                if verified:
                    order.payment_verified = True
                    order.payment_verified_at = payment_time
                    order.status = 'active'
                    order.activated_at = datetime.utcnow()
                    
                    # Set expiration for orders
                    if order.coverage_type == 'XAN' and order.hours:
                        order.expires_at = datetime.utcnow() + timedelta(hours=order.hours)
                    elif order.coverage_type == 'EXTC':
                        order.expires_at = datetime.utcnow() + timedelta(hours=2)
                    
                    verified_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                failed_count += 1
                continue
        
        if verified_count > 0:
            db.session.commit()
        
        return jsonify({
            "success": True,
            "verified": verified_count,
            "failed": failed_count
        }), 200
    
    @app.post("/admin/verify-orders")
    def verify_orders_manual():
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Unauthorized"}), 403
        
        if not admin.api_key:
            flash("Admin API key not configured. Cannot verify orders.", "error")
            return redirect(url_for("admin_panel"))
        
        # Get all pending orders
        pending_orders = Order.query.filter_by(status='pending', payment_verified=False).all()
        
        verified_count = 0
        for order in pending_orders:
            verified, payment_time, event = verify_order_payment(order, admin.api_key)
            
            if verified:
                order.payment_verified = True
                order.payment_verified_at = payment_time
                order.status = 'active'
                order.activated_at = datetime.utcnow()
                
                # Set expiration for orders
                if order.coverage_type == 'XAN' and order.hours:
                    order.expires_at = datetime.utcnow() + timedelta(hours=order.hours)
                elif order.coverage_type == 'EXTC':
                    order.expires_at = datetime.utcnow() + timedelta(hours=2)
                
                verified_count += 1
        
        if verified_count > 0:
            db.session.commit()
            flash(f"✅ Successfully verified {verified_count} order(s)!", "success")
        else:
            flash("No pending payments found to verify.", "info")
        
        return redirect(url_for("admin_panel"))

    @app.post("/admin/orders/expire-now")
    def expire_active_orders_now():
        """Manually expire active orders whose expires_at has passed."""
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Unauthorized"}), 403

        now = datetime.utcnow()

        expired_active = Order.query.filter(
            Order.status == 'active',
            Order.expires_at.isnot(None),
            Order.expires_at < now
        ).all()

        count = 0
        for order in expired_active:
            order.status = 'expired'
            count += 1

        if count > 0:
            db.session.commit()

        return jsonify({"success": True, "expired": count}), 200
    
    @app.post("/admin/toggle-auto-verify")
    def toggle_auto_verify():
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Unauthorized"}), 403
        
        auto_settings = AutoVerifySettings.query.first()
        if not auto_settings:
            auto_settings = AutoVerifySettings(enabled=False)
            db.session.add(auto_settings)
        
        auto_settings.enabled = not auto_settings.enabled
        # When enabling auto-verify, also enable auto-delete and set hours to 144
        if auto_settings.enabled:
            auto_settings.auto_delete_enabled = True
            auto_settings.auto_delete_hours = 144
        db.session.commit()
        
        status = "enabled" if auto_settings.enabled else "disabled"
        if auto_settings.enabled:
            flash("Auto-verification enabled. Auto-delete enabled (144 hours).", "success")
        else:
            flash("Auto-verification disabled.", "success")
        
        return redirect(url_for("admin_panel"))
    
    @app.post("/admin/set-auto-interval")
    def set_auto_interval():
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Unauthorized"}), 403
        
        interval = request.form.get("interval", type=int)
        if not interval or interval < 1:
            flash("Invalid interval. Must be at least 1 second.", "error")
            return redirect(url_for("admin_panel"))
        
        auto_settings = AutoVerifySettings.query.first()
        if not auto_settings:
            auto_settings = AutoVerifySettings()
            db.session.add(auto_settings)
        
        # Store seconds in existing field for compatibility
        auto_settings.interval_minutes = interval
        db.session.commit()
        
        flash(f"Auto-check interval set to {interval} seconds.", "success")
        return redirect(url_for("admin_panel"))
    
    @app.post("/admin/pricing/xan")
    def add_xan_pricing():
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Unauthorized"}), 403
        
        hours = request.form.get("hours", type=int)
        cost = request.form.get("cost", type=int)
        reward = request.form.get("reward", type=int)
        
        if not all([hours, cost, reward]) or hours < 1 or cost < 1 or reward < 1:
            flash("Invalid pricing values.", "error")
            return redirect(url_for("admin_panel"))
        
        # Check if exists
        existing = PricingConfig.query.filter_by(coverage_type='XAN', duration=hours).first()
        if existing:
            existing.cost = cost
            existing.xanax_reward = reward
            existing.active = True
            flash(f"Updated XAN {hours}H pricing.", "success")
        else:
            new_price = PricingConfig(
                coverage_type='XAN',
                duration=hours,
                cost=cost,
                xanax_reward=reward,
                active=True
            )
            db.session.add(new_price)
            flash(f"Added XAN {hours}H pricing.", "success")
        
        db.session.commit()
        return redirect(url_for("admin_panel"))
    
    @app.post("/admin/pricing/extc")
    def add_extc_pricing():
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Unauthorized"}), 403
        
        jumps = request.form.get("jumps", type=int)
        cost = request.form.get("cost", type=int)
        xanax_reward = request.form.get("xanax_reward", type=int)
        edvds_reward = request.form.get("edvds_reward", type=int)
        ecstasy_reward = request.form.get("ecstasy_reward", type=int)
        
        if not all([jumps, cost, xanax_reward, edvds_reward, ecstasy_reward]):
            flash("Invalid pricing values.", "error")
            return redirect(url_for("admin_panel"))
        
        # Check if exists
        existing = PricingConfig.query.filter_by(coverage_type='EXTC', duration=jumps).first()
        if existing:
            existing.cost = cost
            existing.xanax_reward = xanax_reward
            existing.edvds_reward = edvds_reward
            existing.ecstasy_reward = ecstasy_reward
            existing.active = True
            flash(f"Updated EXTC {jumps}J pricing.", "success")
        else:
            new_price = PricingConfig(
                coverage_type='EXTC',
                duration=jumps,
                cost=cost,
                xanax_reward=xanax_reward,
                edvds_reward=edvds_reward,
                ecstasy_reward=ecstasy_reward,
                active=True
            )
            db.session.add(new_price)
            flash(f"Added EXTC {jumps}J pricing.", "success")
        
        db.session.commit()
        return redirect(url_for("admin_panel"))
    
    @app.delete("/admin/pricing/<int:pricing_id>")
    def delete_pricing(pricing_id):
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Unauthorized"}), 403
        
        pricing = PricingConfig.query.get(pricing_id)
        if not pricing:
            return jsonify({"error": "Pricing not found"}), 404
        
        db.session.delete(pricing)
        db.session.commit()
        
        return jsonify({"success": True}), 200
    
    @app.post("/admin/pricing/<int:pricing_id>/edit")
    def edit_pricing(pricing_id):
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Unauthorized"}), 403
        
        pricing = PricingConfig.query.get(pricing_id)
        if not pricing:
            return jsonify({"error": "Pricing not found"}), 404
        
        data = request.get_json()
        cost = data.get("cost", type=int)
        xanax_reward = data.get("xanax_reward", type=int)
        edvds_reward = data.get("edvds_reward")
        ecstasy_reward = data.get("ecstasy_reward")
        active = data.get("active", True)
        
        pricing.cost = cost or pricing.cost
        pricing.xanax_reward = xanax_reward or pricing.xanax_reward
        if edvds_reward is not None:
            pricing.edvds_reward = edvds_reward
        if ecstasy_reward is not None:
            pricing.ecstasy_reward = ecstasy_reward
        pricing.active = active
        
        db.session.commit()
        return jsonify({"success": True}), 200
    
    @app.delete("/admin/order/<int:order_id>")
    def delete_pending_order(order_id):
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Unauthorized"}), 403
        
        order = Order.query.get(order_id)
        if not order:
            return jsonify({"error": "Order not found"}), 404
        
        if order.status != 'pending':
            return jsonify({"error": "Can only delete pending orders"}), 400
        
        db.session.delete(order)
        db.session.commit()
        
        return jsonify({"success": True}), 200
    
    @app.post("/admin/settings/auto-delete")
    def toggle_auto_delete():
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Unauthorized"}), 403
        
        data = request.get_json()
        enabled = data.get("enabled", False)
        auto_delete_hours = data.get("auto_delete_hours", 24)
        
        auto_settings = AutoVerifySettings.query.first()
        if not auto_settings:
            auto_settings = AutoVerifySettings()
            db.session.add(auto_settings)
        
        auto_settings.auto_delete_enabled = enabled
        auto_settings.auto_delete_hours = auto_delete_hours
        
        db.session.commit()
        return jsonify({"success": True}), 200
    
    @app.post("/admin/order/activate-manual")
    def activate_order_manual():
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Unauthorized"}), 403
        
        data = request.get_json()
        
        user_id = data.get("user_id")
        coverage_type = data.get("coverage_type")  # 'XAN' or 'EXTC'
        duration = data.get("duration")  # hours for XAN, jumps for EXTC
        
        # Convert to correct types
        try:
            user_id = int(user_id) if user_id else None
            duration = int(duration) if duration else None
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid data types"}), 400
        
        if not all([user_id, coverage_type, duration]):
            return jsonify({"error": "Missing required fields"}), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        # Get pricing for validation
        pricing = PricingConfig.query.filter_by(
            coverage_type=coverage_type,
            duration=duration,
            active=True
        ).first()
        
        if not pricing:
            return jsonify({"error": "Invalid coverage configuration"}), 400
        
        # Deactivate any existing active coverage of same type for this user
        existing_active = Order.query.filter_by(
            user_id=user.id,
            coverage_type=coverage_type,
            status='active'
        ).first()
        if existing_active:
            existing_active.status = 'completed'
        
        # Delete any pending order of the same type
        existing_pending = Order.query.filter_by(
            user_id=user.id,
            coverage_type=coverage_type,
            status='pending'
        ).first()
        
        if existing_pending:
            db.session.delete(existing_pending)
        
        # Create new active order
        now = datetime.utcnow()
        # XAN orders expire after specified hours, EXTC orders always expire in 2 hours
        expires_at = now + timedelta(hours=duration) if coverage_type == 'XAN' else now + timedelta(hours=2)
        
        order = Order(
            user_id=user.id,
            coverage_type=coverage_type,
            status='active',
            xanax_payment=pricing.cost,
            payment_verified=True,
            payment_verified_at=now,
            activated_at=now,
            expires_at=expires_at,
            hours=duration if coverage_type == 'XAN' else None,
            jumps=duration if coverage_type == 'EXTC' else None,
            xanax_reward=pricing.xanax_reward,
            edvds_reward=pricing.edvds_reward,
            ecstasy_reward=pricing.ecstasy_reward
        )
        
        db.session.add(order)
        db.session.commit()
        
        flash(f"Manually activated {coverage_type} cover for {user.torn_name}", "success")
        return jsonify({"success": True, "order_id": order.id}), 201
    
    @app.get("/admin/leaderboard")
    def leaderboard():
        """Show leaderboard of users by order count - admin only"""
        admin = require_admin()
        if not admin:
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for("home"))
        
        # Get all users with their payment and overdose statistics
        from sqlalchemy import func, case
        
        user_stats = db.session.query(
            User.id,
            User.torn_user_id,
            User.torn_name,
            func.count(Order.id).label('total_orders'),
            func.sum(case(
                (Order.coverage_type == 'XAN', Order.xanax_payment),
                else_=0
            )).label('xan_paid'),
            func.sum(case(
                (Order.coverage_type == 'EXTC', Order.xanax_payment),
                else_=0
            )).label('extc_paid'),
            func.sum(case(
                (Order.status == 'active', 1),
                else_=0
            )).label('active_orders'),
            func.sum(Order.xanax_payment).label('total_xanax_spent')
        ).outerjoin(Order, User.id == Order.user_id).group_by(
            User.id,
            User.torn_user_id,
            User.torn_name
        ).order_by(
            func.count(Order.id).desc()
        ).all()
        
        # Get overdose payouts per user and coverage type
        overdose_stats = db.session.query(
            Overdose.user_id,
            Overdose.coverage_type,
            func.sum(Overdose.payout_xanax).label('total_xanax_payout'),
            func.sum(Overdose.payout_edvds).label('total_edvds_payout'),
            func.sum(Overdose.payout_ecstasy).label('total_ecstasy_payout')
        ).filter(
            Overdose.confirmed == True
        ).group_by(
            Overdose.user_id,
            Overdose.coverage_type
        ).all()
        
        # Create a dictionary for quick lookup of overdose payouts
        overdose_dict = {}
        for stat in overdose_stats:
            key = (stat.user_id, stat.coverage_type)
            overdose_dict[key] = {
                'xanax': stat.total_xanax_payout or 0,
                'edvds': stat.total_edvds_payout or 0,
                'ecstasy': stat.total_ecstasy_payout or 0
            }
        
        # Format results
        leaderboard_data = []
        for rank, user in enumerate(user_stats, 1):
            xan_payout_data = overdose_dict.get((user.id, 'XAN'), {'xanax': 0, 'edvds': 0, 'ecstasy': 0})
            extc_payout_data = overdose_dict.get((user.id, 'EXTC'), {'xanax': 0, 'edvds': 0, 'ecstasy': 0})
            
            leaderboard_data.append({
                'rank': rank,
                'user_id': user.torn_user_id,
                'user_name': user.torn_name,
                'total_orders': user.total_orders or 0,
                'xan_paid': user.xan_paid or 0,
                'extc_paid': user.extc_paid or 0,
                'xan_overdose_payout': xan_payout_data['xanax'],
                'extc_overdose_xanax': extc_payout_data['xanax'],
                'extc_overdose_edvds': extc_payout_data['edvds'],
                'extc_overdose_ecstasy': extc_payout_data['ecstasy'],
                'active_orders': user.active_orders or 0,
                'total_xanax_spent': user.total_xanax_spent or 0
            })
        
        return render_template("leaderboard.html", leaderboard=leaderboard_data, user=admin)
