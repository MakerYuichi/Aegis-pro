from src.config import settings
from loguru import logger

class TwilioService:
    def __init__(self):
        self.account_sid = settings.TWILIO_ACCOUNT_SID
        self.auth_token = settings.TWILIO_AUTH_TOKEN
        self.from_number = settings.TWILIO_FROM_NUMBER
        self.enabled = bool(self.account_sid and self.auth_token)
        logger.info(f"✅ TwilioService initialized (enabled: {self.enabled})")
    
    async def send_sms(self, to_number: str, message: str) -> bool:
        """Send SMS via Twilio"""
        if not self.enabled:
            logger.info(f"📱 [MOCK SMS] To: {to_number} | Message: {message[:50]}...")
            return True
        
        try:
            from twilio.rest import Client
            client = Client(self.account_sid, self.auth_token)
            
            sms = client.messages.create(
                body=message,
                from_=self.from_number,
                to=to_number
            )
            
            logger.info(f"✅ SMS sent to {to_number} (SID: {sms.sid})")
            return True
            
        except Exception as e:
            logger.error(f"SMS error: {e}")
            return False
    
    async def make_call(self, to_number: str, message: str) -> bool:
        """Make a phone call via Twilio"""
        if not self.enabled:
            logger.info(f"📞 [MOCK CALL] To: {to_number} | Message: {message[:50]}...")
            return True
        
        try:
            from twilio.rest import Client
            from twilio.twiml.voice_response import VoiceResponse
            
            client = Client(self.account_sid, self.auth_token)
            
            # Create a simple TwiML response
            response = VoiceResponse()
            response.say(message, voice='alice')
            
            call = client.calls.create(
                twiml=str(response),
                from_=self.from_number,
                to=to_number
            )
            
            logger.info(f"✅ Call made to {to_number} (SID: {call.sid})")
            return True
            
        except Exception as e:
            logger.error(f"Call error: {e}")
            return False
