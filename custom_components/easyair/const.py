"""Constants for the Bosch EasyAir integration."""
from datetime import timedelta

DOMAIN = "easyair"

# Recovered from the Bosch EasyAir Android app (com.idsmobileapp).
AUTH_DOMAIN = "https://auth.smart-climate-ids.com"
CLIENT_ID = "7q2puec5cov7ls93041mb38p6v"
REDIRECT_URI = "idsmobileapp://"
IDENTITY_PROVIDER = "IDS-TTNA"  # Cognito federation to SingleKey ID
SCOPES = "phone email openid profile aws.cognito.signin.user.admin"
API_BASE = "https://api.smart-climate-ids.com"

CONF_TOKENS = "tokens"
UPDATE_INTERVAL = timedelta(minutes=30)
