from src.config import settings
from loguru import logger
import httpx
import json

class PagerDutyService:
    def __init__(self):
        self.api_key = settings.PAGERDUTY_API_KEY
        self.enabled = bool(self.api_key)
        logger.info(f"✅ PagerDuty service initialized (enabled: {self.enabled})")
    
    async def create_incident(self, incident_data: dict) -> dict:
        """
        Create an incident in PagerDuty (mock if no API key)
        """
        if not self.enabled:
            return self._mock_response(incident_data)
        
        try:
            # PagerDuty API endpoint
            url = "https://api.pagerduty.com/incidents"
            
            headers = {
                "Authorization": f"Token token={self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            payload = {
                "incident": {
                    "type": "incident",
                    "title": incident_data.get('title', 'AEGIS PRO Alert'),
                    "service": {
                        "id": settings.PAGERDUTY_SERVICE_ID,
                        "type": "service_reference"
                    },
                    "body": {
                        "type": "incident_body",
                        "details": incident_data.get('root_cause', 'No details provided')
                    }
                }
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload)
                
                if response.status_code == 201:
                    data = response.json()
                    logger.info(f"✅ PagerDuty incident created: {data.get('incident', {}).get('id')}")
                    return {
                        "status": "created",
                        "pagerduty_id": data.get('incident', {}).get('id'),
                        "url": data.get('incident', {}).get('html_url')
                    }
                else:
                    logger.error(f"PagerDuty error: {response.status_code} - {response.text}")
                    return self._mock_response(incident_data)
                    
        except Exception as e:
            logger.error(f"PagerDuty error: {e}")
            return self._mock_response(incident_data)
    
    def _mock_response(self, incident_data: dict) -> dict:
        """Mock PagerDuty response (when API key not set)"""
        return {
            "status": "mock_created",
            "pagerduty_id": f"PD-MOCK-{incident_data.get('incident_id', '0000')[:8]}",
            "url": "https://mock.pagerduty.com/incidents/mock",
            "mock": True
        }
    
    async def acknowledge_incident(self, pagerduty_id: str) -> dict:
        """Acknowledge an incident in PagerDuty"""
        if not self.enabled:
            return {"status": "mock_acknowledged", "mock": True}
        
        try:
            url = f"https://api.pagerduty.com/incidents/{pagerduty_id}"
            headers = {
                "Authorization": f"Token token={self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            payload = {
                "incident": {
                    "status": "acknowledged"
                }
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.put(url, headers=headers, json=payload)
                
                if response.status_code == 200:
                    logger.info(f"✅ PagerDuty incident acknowledged: {pagerduty_id}")
                    return {"status": "acknowledged"}
                else:
                    logger.error(f"PagerDuty ack error: {response.status_code}")
                    return {"status": "mock_acknowledged", "mock": True}
                    
        except Exception as e:
            logger.error(f"PagerDuty ack error: {e}")
            return {"status": "mock_acknowledged", "mock": True}
