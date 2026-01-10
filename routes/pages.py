from flask import render_template, redirect, url_for, session
from sqlalchemy import func, case


def init_page_routes(app, db, User, Order, PricingConfig, Overdose=None):
    @app.get("/")
    def home():
        if session.get("user_id"):
            return redirect(url_for("dashboard"))
        return render_template("home.html")

    @app.get("/dashboard")
    def dashboard():
        uid = session.get("user_id")
        if not uid:
            return redirect(url_for("home"))

        user = User.query.get(uid)
        if not user:
            session.clear()
            return redirect(url_for("home"))
        
        # Get pricing configurations
        xan_prices = PricingConfig.query.filter_by(
            coverage_type='XAN',
            active=True
        ).order_by(PricingConfig.duration).all()
        
        extc_prices = PricingConfig.query.filter_by(
            coverage_type='EXTC',
            active=True
        ).order_by(PricingConfig.duration).all()
        
        # Get user's current orders
        pending_order = Order.query.filter_by(
            user_id=user.id,
            status='pending'
        ).first()
        
        # Get active orders by type
        active_xan_order = Order.query.filter_by(
            user_id=user.id,
            coverage_type='XAN',
            status='active'
        ).first()
        
        active_extc_order = Order.query.filter_by(
            user_id=user.id,
            coverage_type='EXTC',
            status='active'
        ).first()

        return render_template(
            "dashboard.html",
            user=user,
            xan_prices=xan_prices,
            extc_prices=extc_prices,
            pending_order=pending_order,
            active_xan_order=active_xan_order,
            active_extc_order=active_extc_order
        )
    
    @app.get("/user/history")
    def user_history():
        """Show user's personal order and overdose history"""
        uid = session.get("user_id")
        if not uid:
            return redirect(url_for("home"))
        
        user = User.query.get(uid)
        if not user:
            session.clear()
            return redirect(url_for("home"))
        
        # Get all user's orders
        all_orders = Order.query.filter_by(user_id=user.id).order_by(Order.created_at.desc()).all()
        
        # Calculate statistics
        order_stats = db.session.query(
            func.count(Order.id).label('total_orders'),
            func.sum(case(
                (Order.coverage_type == 'XAN', Order.xanax_payment),
                else_=0
            )).label('xan_paid'),
            func.sum(case(
                (Order.coverage_type == 'EXTC', Order.xanax_payment),
                else_=0
            )).label('extc_paid'),
            func.sum(Order.xanax_payment).label('total_spent')
        ).filter(Order.user_id == user.id).first()
        
        # Get all user's overdoses
        all_overdoses = []
        if Overdose:
            all_overdoses = Overdose.query.filter_by(user_id=user.id).order_by(Overdose.reported_at.desc()).all()
        
        # Calculate overdose statistics
        overdose_stats = db.session.query(
            Overdose.coverage_type,
            func.count(Overdose.id).label('total_reports'),
            func.count(case((Overdose.confirmed == True, 1))).label('confirmed_count'),
            func.sum(case((Overdose.confirmed == True, Overdose.payout_xanax))).label('xan_payout'),
            func.sum(case((Overdose.confirmed == True, Overdose.payout_edvds))).label('edvds_payout'),
            func.sum(case((Overdose.confirmed == True, Overdose.payout_ecstasy))).label('ecstasy_payout')
        ).filter(Overdose.user_id == user.id).group_by(Overdose.coverage_type).all() if Overdose else []
        
        # Format overdose stats
        overdose_summary = {}
        for stat in overdose_stats:
            overdose_summary[stat.coverage_type] = {
                'total_reports': stat.total_reports or 0,
                'confirmed_count': stat.confirmed_count or 0,
                'xan_payout': stat.xan_payout or 0,
                'edvds_payout': stat.edvds_payout or 0,
                'ecstasy_payout': stat.ecstasy_payout or 0
            }
        
        return render_template(
            "user_history.html",
            user=user,
            all_orders=all_orders,
            all_overdoses=all_overdoses,
            order_stats=order_stats,
            overdose_summary=overdose_summary
        )
