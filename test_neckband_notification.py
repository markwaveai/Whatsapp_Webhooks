from neckband_router import send_neckband_notifications
import datetime

payload = {
    "deviceid": "S1IAD1881",
    "FarmName": "VestFar R&D",
    "farmid": "797",
    "msg_title": None,
    "msg_body": None,
    "alert_type": "regular",
    "notification_type": "HEALTH",
    "cdate_hr": "1771303130",
    "timestamp": "2026-02-17T04:38:50.184956"
}

print("Testing send_neckband_notifications...")
send_neckband_notifications(payload)
print("Test completed.")
