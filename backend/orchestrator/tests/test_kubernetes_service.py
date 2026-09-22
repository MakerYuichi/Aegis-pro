"""
Tests for src/services/kubernetes_service.py.

Covers:
  - Initialization with/without K8S credentials
  - rollback_deployment: mock mode, real kubectl mode, error paths
  - get_deployment_status: mock mode, real kubectl mode, error paths
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.kubernetes_service import KubernetesService


@pytest.fixture
def service():
    """KubernetesService with credentials."""
    with patch("src.services.kubernetes_service.settings") as settings:
        settings.K8S_API_URL = "https://k8s.example.com"
        settings.K8S_TOKEN = "test-token"
        settings.K8S_NAMESPACE = "production"
        
        svc = KubernetesService()
    return svc


@pytest.fixture
def service_no_creds():
    """KubernetesService without credentials (mock mode)."""
    with patch("src.services.kubernetes_service.settings") as settings:
        settings.K8S_API_URL = None
        settings.K8S_TOKEN = None
        settings.K8S_NAMESPACE = None
        
        svc = KubernetesService()
    return svc


@pytest.fixture
def service_custom_namespace():
    """KubernetesService with custom namespace."""
    with patch("src.services.kubernetes_service.settings") as settings:
        settings.K8S_API_URL = "https://k8s.example.com"
        settings.K8S_TOKEN = "test-token"
        settings.K8S_NAMESPACE = "staging"
        
        svc = KubernetesService()
    return svc


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def test_init_with_credentials():
    """
    Situation: K8S credentials configured.
    Expected: Service available with credentials.
    Function: src.services.kubernetes_service.KubernetesService.__init__
    """
    with patch("src.services.kubernetes_service.settings") as settings:
        settings.K8S_API_URL = "https://k8s.example.com"
        settings.K8S_TOKEN = "test-token"
        settings.K8S_NAMESPACE = "production"
        
        svc = KubernetesService()
        
        assert svc.k8s_api_url == "https://k8s.example.com"
        assert svc.k8s_token == "test-token"
        assert svc.namespace == "production"
        assert svc.available is True


def test_init_without_credentials():
    """
    Situation: K8S credentials not configured.
    Expected: Service unavailable (mock mode).
    Function: src.services.kubernetes_service.KubernetesService.__init__
    """
    with patch("src.services.kubernetes_service.settings") as settings:
        settings.K8S_API_URL = None
        settings.K8S_TOKEN = None
        settings.K8S_NAMESPACE = None
        
        svc = KubernetesService()
        
        assert svc.available is False


def test_init_default_namespace():
    """
    Situation: K8S_NAMESPACE not set.
    Expected: Defaults to "production".
    Function: src.services.kubernetes_service.KubernetesService.__init__
    """
    with patch("src.services.kubernetes_service.settings") as settings:
        settings.K8S_API_URL = "https://k8s.example.com"
        settings.K8S_TOKEN = "test-token"
        settings.K8S_NAMESPACE = None
        
        svc = KubernetesService()
        
        assert svc.namespace == "production"


# ---------------------------------------------------------------------------
# rollback_deployment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rollback_deployment_mock_mode(service_no_creds):
    """
    Situation: K8S credentials not configured.
    Expected: Returns mock rollback response.
    Function: src.services.kubernetes_service.KubernetesService.rollback_deployment
    """
    result = await service_no_creds.rollback_deployment("payment-service")
    
    assert result["status"] == "mock_rollback"
    assert result["service"] == "payment-service"
    assert result["mock"] is True
    assert "kubectl" in result["command"]


@pytest.mark.asyncio
async def test_rollback_deployment_success(service):
    """
    Situation: K8S credentials configured, rollback succeeds.
    Expected: Returns success with revision info.
    Function: src.services.kubernetes_service.KubernetesService.rollback_deployment
    """
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"status": {"revisions": [{"revision": 2}]}}'
    
    with patch("src.services.kubernetes_service.subprocess.run", return_value=mock_result):
        result = await service.rollback_deployment("payment-service")
    
    assert result["status"] == "rollback_successful"
    assert result["service"] == "payment-service"
    assert result["from_revision"] == 2
    assert result["to_revision"] == 1


@pytest.mark.asyncio
async def test_rollback_deployment_get_revision_fails(service):
    """
    Situation: kubectl get revision fails.
    Expected: Returns error.
    Function: src.services.kubernetes_service.KubernetesService.rollback_deployment
    """
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "deployment not found"
    
    with patch("src.services.kubernetes_service.subprocess.run", return_value=mock_result):
        result = await service.rollback_deployment("payment-service")
    
    assert "error" in result
    assert "Failed to get revision" in result["error"]


@pytest.mark.asyncio
async def test_rollback_deployment_no_revisions(service):
    """
    Situation: Deployment has no revision history.
    Expected: Returns error.
    Function: src.services.kubernetes_service.KubernetesService.rollback_deployment
    """
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"status": {"revisions": []}}'
    
    with patch("src.services.kubernetes_service.subprocess.run", return_value=mock_result):
        result = await service.rollback_deployment("payment-service")
    
    assert "error" in result
    assert "No revisions found" in result["error"]


@pytest.mark.asyncio
async def test_rollback_deployment_no_previous_revision(service):
    """
    Situation: Deployment at revision 1 (no previous).
    Expected: Returns error.
    Function: src.services.kubernetes_service.KubernetesService.rollback_deployment
    """
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"status": {"revisions": [{"revision": 1}]}}'
    
    with patch("src.services.kubernetes_service.subprocess.run", return_value=mock_result):
        result = await service.rollback_deployment("payment-service")
    
    assert "error" in result
    assert "No previous revision" in result["error"]


@pytest.mark.asyncio
async def test_rollback_deployment_rollback_command_fails(service):
    """
    Situation: kubectl rollback command fails.
    Expected: Returns error.
    Function: src.services.kubernetes_service.KubernetesService.rollback_deployment
    """
    mock_get_result = MagicMock()
    mock_get_result.returncode = 0
    mock_get_result.stdout = '{"status": {"revisions": [{"revision": 2}]}}'
    
    mock_rollback_result = MagicMock()
    mock_rollback_result.returncode = 1
    mock_rollback_result.stderr = "rollback failed"
    
    with patch("src.services.kubernetes_service.subprocess.run") as mock_run:
        mock_run.side_effect = [mock_get_result, mock_rollback_result]
        result = await service.rollback_deployment("payment-service")
    
    assert "error" in result
    assert "Rollback failed" in result["error"]


@pytest.mark.asyncio
async def test_rollback_deployment_fallback_to_simple_rollback(service):
    """
    Situation: JSON parsing fails, falls back to simple rollback.
    Expected: Attempts simple rollback.
    Function: src.services.kubernetes_service.KubernetesService.rollback_deployment
    """
    mock_get_result = MagicMock()
    mock_get_result.returncode = 0
    mock_get_result.stdout = "invalid json"
    
    mock_rollback_result = MagicMock()
    mock_rollback_result.returncode = 0
    mock_rollback_result.stdout = "rolled back"
    
    with patch("src.services.kubernetes_service.subprocess.run") as mock_run:
        mock_run.side_effect = [mock_get_result, mock_rollback_result]
        result = await service.rollback_deployment("payment-service")
    
    assert result["status"] == "rollback_successful"


@pytest.mark.asyncio
async def test_rollback_deployment_custom_namespace(service_custom_namespace):
    """
    Situation: Custom namespace configured.
    Expected: Uses custom namespace in kubectl commands.
    Function: src.services.kubernetes_service.KubernetesService.rollback_deployment
    """
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"status": {"revisions": [{"revision": 2}]}}'
    
    with patch("src.services.kubernetes_service.subprocess.run", return_value=mock_result) as mock_run:
        await service_custom_namespace.rollback_deployment("payment-service")
        
        # Check that namespace is used in commands
        calls = mock_run.call_args_list
        assert any("-n staging" in str(call) for call in calls)


# ---------------------------------------------------------------------------
# get_deployment_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_deployment_status_mock_mode(service_no_creds):
    """
    Situation: K8S credentials not configured.
    Expected: Returns mock status.
    Function: src.services.kubernetes_service.KubernetesService.get_deployment_status
    """
    result = await service_no_creds.get_deployment_status("payment-service")
    
    assert result["status"] == "mock"
    assert result["service"] == "payment-service"
    assert result["mock"] is True


@pytest.mark.asyncio
async def test_get_deployment_status_success(service):
    """
    Situation: K8S credentials configured, kubectl succeeds.
    Expected: Returns deployment status with replica counts.
    Function: src.services.kubernetes_service.KubernetesService.get_deployment_status
    """
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"status": {"readyReplicas": 3, "replicas": 3, "availableReplicas": 3, "updatedReplicas": 3, "conditions": []}}'
    
    with patch("src.services.kubernetes_service.subprocess.run", return_value=mock_result):
        result = await service.get_deployment_status("payment-service")
    
    assert result["service"] == "payment-service"
    assert result["ready_replicas"] == 3
    assert result["replicas"] == 3
    assert result["available_replicas"] == 3
    assert result["updated_replicas"] == 3


@pytest.mark.asyncio
async def test_get_deployment_status_kubectl_fails(service):
    """
    Situation: kubectl command fails.
    Expected: Returns error.
    Function: src.services.kubernetes_service.KubernetesService.get_deployment_status
    """
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "deployment not found"
    
    with patch("src.services.kubernetes_service.subprocess.run", return_value=mock_result):
        result = await service.get_deployment_status("payment-service")
    
    assert "error" in result
    assert "Failed to get status" in result["error"]


@pytest.mark.asyncio
async def test_get_deployment_status_invalid_json(service):
    """
    Situation: kubectl returns invalid JSON.
    Expected: Returns parse error.
    Function: src.services.kubernetes_service.KubernetesService.get_deployment_status
    """
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "not json"
    
    with patch("src.services.kubernetes_service.subprocess.run", return_value=mock_result):
        result = await service.get_deployment_status("payment-service")
    
    assert "error" in result
    assert "Failed to parse status" in result["error"]


@pytest.mark.asyncio
async def test_get_deployment_status_missing_status_key(service):
    """
    Situation: JSON missing status key.
    Expected: Returns parse error.
    Function: src.services.kubernetes_service.KubernetesService.get_deployment_status
    """
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"metadata": {}}'
    
    with patch("src.services.kubernetes_service.subprocess.run", return_value=mock_result):
        result = await service.get_deployment_status("payment-service")
    
    # Should return dict with default values
    assert result["service"] == "payment-service"
    assert result["ready_replicas"] == 0


@pytest.mark.asyncio
async def test_get_deployment_status_custom_namespace(service_custom_namespace):
    """
    Situation: Custom namespace configured.
    Expected: Uses custom namespace in kubectl command.
    Function: src.services.kubernetes_service.KubernetesService.get_deployment_status
    """
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"status": {}}'
    
    with patch("src.services.kubernetes_service.subprocess.run", return_value=mock_result) as mock_run:
        await service_custom_namespace.get_deployment_status("payment-service")
        
        # Check that namespace is used in command
        call_str = str(mock_run.call_args)
        assert "-n staging" in call_str
