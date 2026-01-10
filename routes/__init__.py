def register_routes(app, db, User, Order, PricingConfig, AutoVerifySettings, Overdose, fetch_torn_basic, admin_torn_id, mod_torn_ids):
    from .auth import init_auth_routes
    from .pages import init_page_routes
    from .admin import init_admin_routes
    from .orders import init_order_routes
    from .overdose import init_overdose_routes

    init_auth_routes(app, db, User, fetch_torn_basic, admin_torn_id, mod_torn_ids)
    init_page_routes(app, db, User, Order, PricingConfig, Overdose)
    init_admin_routes(app, db, User, Order, PricingConfig, AutoVerifySettings, Overdose)
    init_order_routes(app, db, User, Order, PricingConfig)
    init_overdose_routes(app, db, User, Order, Overdose)
