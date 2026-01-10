"""
Order verification service - handles Torn API checks for insurance orders
"""
import re
from datetime import datetime, timedelta
import requests


def fetch_torn_events(api_key: str) -> dict:
    """Fetch user events from Torn API"""
    try:
        url = f"https://api.torn.com/user/?selections=events&key={api_key}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, dict) and "error" in data:
            raise ValueError(data["error"].get("error", "Torn API error"))
        
        return data.get("events", {})
    except Exception as e:
        print(f"Error fetching Torn events: {e}")
        return {}


def verify_order_payment(order, admin_api_key: str) -> tuple:
    """
    Verify if payment for an order has been received via Torn API
    Returns: (verified: bool, payment_time: datetime or None, matched_event: dict or None)
    """
    if not admin_api_key:
        return False, None, None
    
    events = fetch_torn_events(admin_api_key)
    if not events:
        return False, None, None
    
    # Determine message code based on coverage type
    message_code = 'HJSx' if order.coverage_type == 'XAN' else 'HJSe'
    expected_payment = order.xanax_payment
    
    # Get user's Torn name for matching
    user_torn_name = order.user.torn_name.lower()
    
    # 24-hour lookback window
    current_time = datetime.utcnow()
    lookback_limit = current_time - timedelta(hours=24)
    
    # Process events
    log_items = []
    if isinstance(events, dict):
        log_items = list(events.items())
    elif isinstance(events, list):
        log_items = [(i, entry) for i, entry in enumerate(events)]
    
    for log_id, log_entry in log_items:
        if not isinstance(log_entry, dict):
            continue
        
        # Get log text
        log_text = log_entry.get('log', '') or log_entry.get('event', '')
        if not isinstance(log_text, str):
            log_text = str(log_text)
        
        log_text_lower = log_text.lower()
        
        # Get timestamp
        log_timestamp = log_entry.get('timestamp', 0)
        if not log_timestamp:
            continue
        
        log_time = datetime.fromtimestamp(log_timestamp)
        
        # Skip old entries
        if log_time < lookback_limit:
            continue
        
        # Check for required components
        has_xanax = 'xanax' in log_text_lower
        has_message_code = message_code.lower() in log_text_lower
        has_transfer = (
            ('sent' in log_text_lower and 'to you' in log_text_lower) or
            'you were sent' in log_text_lower or
            'received' in log_text_lower
        )
        
        if not (has_xanax and has_message_code and has_transfer):
            continue
        
        # Verify payment amount
        payment_match = False
        xanax_pattern = re.search(r'(\d+)x?\s*xanax', log_text_lower)
        if xanax_pattern:
            found_amount = int(xanax_pattern.group(1))
            payment_match = (found_amount == expected_payment)
        elif 'some xanax' in log_text_lower and expected_payment == 1:
            payment_match = True
        
        if not payment_match:
            continue
        
        # Verify sender name
        name_match = user_torn_name in log_text_lower
        if not name_match:
            # Try partial matching
            name_words = user_torn_name.split()
            name_match = any(word in log_text_lower for word in name_words if len(word) > 2)
        
        if not name_match:
            continue
        
        # All checks passed - payment verified
        return True, log_time, {
            'log_text': log_text,
            'timestamp': log_time,
            'log_id': str(log_id)
        }
    
    return False, None, None


def auto_detect_new_orders(admin_api_key: str, existing_user_ids: set) -> list:
    """
    Auto-detect new insurance orders from Torn API events
    Returns list of detected orders with user info
    """
    if not admin_api_key:
        return []
    
    events = fetch_torn_events(admin_api_key)
    if not events:
        return []
    
    detected_orders = []
    current_time = datetime.utcnow()
    lookback_limit = current_time - timedelta(hours=1)  # Only last hour for auto-detection
    
    # Process events
    log_items = []
    if isinstance(events, dict):
        log_items = list(events.items())
    elif isinstance(events, list):
        log_items = [(i, entry) for i, entry in enumerate(events)]
    
    for log_id, log_entry in log_items:
        if not isinstance(log_entry, dict):
            continue
        
        log_text = log_entry.get('log', '') or log_entry.get('event', '')
        if not isinstance(log_text, str):
            log_text = str(log_text)
        
        log_text_lower = log_text.lower()
        log_timestamp = log_entry.get('timestamp', 0)
        
        if not log_timestamp:
            continue
        
        log_time = datetime.fromtimestamp(log_timestamp)
        
        if log_time < lookback_limit:
            continue
        
        # Check for insurance orders
        has_xanax = 'xanax' in log_text_lower
        has_hjsx = 'hjsx' in log_text_lower
        has_hjse = 'hjse' in log_text_lower
        has_transfer = (
            ('sent' in log_text_lower and 'to you' in log_text_lower) or
            'you were sent' in log_text_lower or
            'received' in log_text_lower
        )
        
        is_xan_order = has_xanax and has_hjsx and has_transfer
        is_extc_order = has_xanax and has_hjse and has_transfer
        
        if not (is_xan_order or is_extc_order):
            continue
        
        # Extract sender name
        sender_name = None
        name_match = re.search(r'from.*?>([^<]+)</a>', log_text)
        if name_match:
            sender_name = name_match.group(1).strip()
        else:
            parts = log_text.split(' from ')
            if len(parts) > 1:
                name_part = parts[1].split(' with')[0].strip()
                sender_name = name_part.split()[0]
        
        if not sender_name:
            continue
        
        # Extract payment amount
        payment_amount = 0
        xanax_pattern = re.search(r'(\d+)x?\s*xanax', log_text_lower)
        if xanax_pattern:
            payment_amount = int(xanax_pattern.group(1))
        elif 'some xanax' in log_text_lower:
            payment_amount = 1
        
        if payment_amount == 0:
            continue
        
        detected_orders.append({
            'sender_name': sender_name,
            'coverage_type': 'XAN' if is_xan_order else 'EXTC',
            'payment_amount': payment_amount,
            'timestamp': log_time,
            'log_text': log_text
        })
    
    return detected_orders
