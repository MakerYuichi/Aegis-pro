from loguru import logger
import subprocess
import json
from src.config import settings

class KubernetesService:
    def __init__(self):
        self.k8s_api_url = settings.K8S_API_URL
        self.k8s_token = settings.K8S_TOKEN
        self.namespace = settings.K8S_NAMESPACE or "production"
        self.available = bool(self.k8s_api_url and self.k8s_token)
        
        if not self.available:
            logger.warning("⚠️ Kubernetes credentials not configured. Using mock mode.")
        else:
            logger.info("✅ KubernetesService initialized")
    
    async def rollback_deployment(self, service_name: str) -> dict:
        """Rollback a Kubernetes deployment"""
        if not self.available:
            logger.info(f"🔧 [MOCK] Rollback {service_name} in {self.namespace}")
            return {
                "status": "mock_rollback",
                "service": service_name,
                "namespace": self.namespace,
                "message": f"✅ [MOCK] Rollbacked {service_name} (no K8s credentials)",
                "command": f"kubectl rollout undo deployment/{service_name} -n {self.namespace}",
                "mock": True
            }
        
        try:
            # Real rollback with kubectl
            cmd_get_revision = f"kubectl rollout history deployment/{service_name} -n {self.namespace} --output=json"
            result = subprocess.run(cmd_get_revision, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                return {"error": f"Failed to get revision: {result.stderr}"}
            
            try:
                data = json.loads(result.stdout)
                revisions = data.get('status', {}).get('revisions', [])
                if not revisions:
                    return {"error": "No revisions found"}
                
                current_revision = revisions[-1].get('revision', 0)
                previous_revision = current_revision - 1
                
                if previous_revision < 1:
                    return {"error": "No previous revision to rollback to"}
                
                cmd_rollback = f"kubectl rollout undo deployment/{service_name} -n {self.namespace}"
                result = subprocess.run(cmd_rollback, shell=True, capture_output=True, text=True)
                
                if result.returncode != 0:
                    return {"error": f"Rollback failed: {result.stderr}"}
                
                return {
                    "status": "rollback_successful",
                    "service": service_name,
                    "namespace": self.namespace,
                    "from_revision": current_revision,
                    "to_revision": previous_revision,
                    "message": f"✅ Rollbacked from revision {current_revision} to {previous_revision}"
                }
                
            except Exception as e:
                # Fallback
                cmd_rollback = f"kubectl rollout undo deployment/{service_name} -n {self.namespace}"
                result = subprocess.run(cmd_rollback, shell=True, capture_output=True, text=True)
                
                if result.returncode != 0:
                    return {"error": f"Rollback failed: {result.stderr}"}
                
                return {
                    "status": "rollback_successful",
                    "service": service_name,
                    "namespace": self.namespace,
                    "message": "✅ Rollbacked to previous revision"
                }
            
        except Exception as e:
            logger.error(f"Kubernetes rollback error: {e}")
            return {"error": str(e)}
    
    async def get_deployment_status(self, service_name: str) -> dict:
        """Get deployment status"""
        if not self.available:
            return {
                "status": "mock",
                "service": service_name,
                "namespace": self.namespace,
                "message": "Kubernetes credentials not configured",
                "mock": True
            }
        
        try:
            cmd = f"kubectl get deployment/{service_name} -n {self.namespace} -o json"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                return {"error": f"Failed to get status: {result.stderr}"}
            
            try:
                data = json.loads(result.stdout)
                status = data.get('status', {})
                
                return {
                    "service": service_name,
                    "namespace": self.namespace,
                    "ready_replicas": status.get('readyReplicas', 0),
                    "replicas": status.get('replicas', 0),
                    "available_replicas": status.get('availableReplicas', 0),
                    "updated_replicas": status.get('updatedReplicas', 0),
                    "conditions": status.get('conditions', [])
                }
            except:
                return {"error": "Failed to parse status"}
                
        except Exception as e:
            logger.error(f"Error getting deployment status: {e}")
            return {"error": str(e)}
