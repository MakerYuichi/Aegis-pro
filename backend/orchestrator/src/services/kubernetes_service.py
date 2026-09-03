from loguru import logger
import httpx
import json
from src.config import settings

class KubernetesService:
    def __init__(self):
        self.k8s_api_url = settings.K8S_API_URL
        self.k8s_token = settings.K8S_TOKEN
        self.namespace = settings.K8S_NAMESPACE or "production"
        logger.info("✅ KubernetesService initialized")
    
    async def rollback_deployment(self, service_name: str) -> dict:
        """
        Rollback a Kubernetes deployment to the previous revision
        Uses kubectl via subprocess or K8s API
        """
        try:
            # For demo purposes, we'll use kubectl
            # In production, use the Kubernetes API
            import subprocess
            
            # Get current revision
            cmd_get_revision = f"kubectl rollout history deployment/{service_name} -n {self.namespace} --output=json"
            result = subprocess.run(cmd_get_revision, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                return {"error": f"Failed to get revision: {result.stderr}"}
            
            # Parse the output to get current revision number
            try:
                import json
                data = json.loads(result.stdout)
                revisions = data.get('status', {}).get('revisions', [])
                if not revisions:
                    return {"error": "No revisions found"}
                
                current_revision = revisions[-1].get('revision', 0)
                previous_revision = current_revision - 1
                
                if previous_revision < 1:
                    return {"error": "No previous revision to rollback to"}
                
                # Execute rollback
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
                # Fallback: Try simple kubectl command without JSON parsing
                cmd_rollback = f"kubectl rollout undo deployment/{service_name} -n {self.namespace}"
                result = subprocess.run(cmd_rollback, shell=True, capture_output=True, text=True)
                
                if result.returncode != 0:
                    return {"error": f"Rollback failed: {result.stderr}"}
                
                return {
                    "status": "rollback_successful",
                    "service": service_name,
                    "namespace": self.namespace,
                    "message": "✅ Rollbacked to previous revision (kubectl)"
                }
            
        except Exception as e:
            logger.error(f"Kubernetes rollback error: {e}")
            return {"error": str(e)}
    
    async def get_deployment_status(self, service_name: str) -> dict:
        """Get deployment status"""
        try:
            import subprocess
            
            cmd = f"kubectl get deployment/{service_name} -n {self.namespace} -o json"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                return {"error": f"Failed to get status: {result.stderr}"}
            
            try:
                import json
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
