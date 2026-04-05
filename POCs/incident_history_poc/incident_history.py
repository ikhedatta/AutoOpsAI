"""
POC #5: Incident History & Context

Searchable incident history for playbook matching.
- Store resolved incidents (in-memory + MongoDB persistence)
- Search for similar incidents by symptom
- Auto-suggest matching playbook
- Cache to prevent memory bloat
"""

import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from enum import Enum
import json

logger = logging.getLogger("autoopsai.incident_history")


class IncidentStatus(Enum):
    """Status of an incident."""
    DETECTED = "detected"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    FAILED = "failed"


@dataclass
class IncidentContext:
    """Context about an incident."""
    incident_id: str
    detected_at: datetime
    symptom: str  # Human-readable symptom description
    container: Optional[str] = None
    service: Optional[str] = None
    error_message: Optional[str] = None
    metrics: Dict[str, Any] = None  # CPU, memory, etc.
    
    def __post_init__(self):
        if self.metrics is None:
            self.metrics = {}


@dataclass
class ResolvedIncident:
    """A successfully resolved incident."""
    incident_id: str
    context: IncidentContext
    playbook_id: str
    playbook_name: str
    remediation_steps: List[str]
    status: IncidentStatus
    resolved_at: datetime
    resolution_time_seconds: float
    approval_count: int = 0
    user_approvals: List[str] = None
    
    def __post_init__(self):
        if self.user_approvals is None:
            self.user_approvals = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data['context'] = asdict(self.context)
        data['context']['detected_at'] = self.context.detected_at.isoformat()
        data['resolved_at'] = self.resolved_at.isoformat()
        data['status'] = self.status.value
        return data


class IncidentHistory:
    """Searchable history of resolved incidents, backed by MongoDB."""
    
    MAX_HISTORY_ITEMS = int(os.getenv("MAX_HISTORY_ITEMS", "1000"))
    
    def __init__(self, use_db: bool = True):
        """Initialize incident history.
        
        Args:
            use_db: If True, persist to MongoDB. Falls back to in-memory on errors.
        """
        self.incidents: List[ResolvedIncident] = []
        self._use_db = use_db
        self._db_available = False
        if use_db:
            try:
                from POCs.persistence import health_check, ensure_indexes
                self._db_available = health_check()
                if self._db_available:
                    ensure_indexes()
                    logger.info("IncidentHistory: MongoDB persistence enabled")
                else:
                    logger.warning("IncidentHistory: MongoDB unavailable, using in-memory only")
            except Exception:
                logger.warning("IncidentHistory: MongoDB init failed, using in-memory only", exc_info=True)
    
    def add(self, incident: ResolvedIncident) -> None:
        """Add resolved incident to history."""
        self.incidents.insert(0, incident)  # Newest first
        
        # Trim to max size
        if len(self.incidents) > self.MAX_HISTORY_ITEMS:
            self.incidents = self.incidents[:self.MAX_HISTORY_ITEMS]
        
        # Persist to MongoDB
        if self._db_available:
            try:
                from POCs.persistence import save_incident
                save_incident(incident.to_dict())
            except Exception:
                logger.warning("Failed to persist incident %s to MongoDB", incident.incident_id, exc_info=True)
    
    def find_similar(
        self,
        symptom: str,
        container: Optional[str] = None,
        service: Optional[str] = None,
        limit: int = 5,
    ) -> List[ResolvedIncident]:
        """
        Find similar incidents by symptom/context.
        
        Args:
            symptom: Symptom to search for
            container: Optional container filter
            service: Optional service filter
            limit: Max results to return
        
        Returns:
            List of similar incidents
        """
        results = []
        symptom_lower = symptom.lower()
        
        for incident in self.incidents:
            # Check if symptom matches
            if symptom_lower not in incident.context.symptom.lower():
                continue
            
            # Check optional filters
            if container and incident.context.container != container:
                continue
            if service and incident.context.service != service:
                continue
            
            results.append(incident)
            
            if len(results) >= limit:
                break
        
        return results
    
    def find_by_playbook(self, playbook_id: str) -> List[ResolvedIncident]:
        """Find all incidents resolved by a playbook."""
        return [i for i in self.incidents if i.playbook_id == playbook_id]
    
    def get_playbook_stats(self, playbook_id: str) -> Dict[str, Any]:
        """Get statistics for a playbook."""
        # Try MongoDB first for more complete stats
        if self._db_available:
            try:
                from POCs.persistence import get_playbook_stats as db_stats
                return db_stats(playbook_id)
            except Exception:
                logger.warning("MongoDB playbook stats failed, falling back to in-memory", exc_info=True)

        incidents = self.find_by_playbook(playbook_id)
        
        if not incidents:
            return {
                "playbook_id": playbook_id,
                "usage_count": 0,
                "success_count": 0,
                "success_rate": 0.0,
                "avg_resolution_time_seconds": 0.0,
            }
        
        success_count = len([i for i in incidents if i.status == IncidentStatus.RESOLVED])
        resolution_times = [i.resolution_time_seconds for i in incidents]
        avg_time = sum(resolution_times) / len(resolution_times) if resolution_times else 0
        
        return {
            "playbook_id": playbook_id,
            "usage_count": len(incidents),
            "success_count": success_count,
            "success_rate": success_count / len(incidents) if incidents else 0,
            "avg_resolution_time_seconds": avg_time,
        }
    
    def export(self, output_file: str = "incident_history.json") -> None:
        """Export history to JSON file."""
        export_data = {
            "exported_at": datetime.now().isoformat(),
            "total_incidents": len(self.incidents),
            "incidents": [i.to_dict() for i in self.incidents],
        }
        
        with open(output_file, 'w') as f:
            json.dump(export_data, f, indent=2, default=str)
    
    def clear(self) -> None:
        """Clear all history (for testing)."""
        self.incidents.clear()
    
    def get_recent(self, hours: int = 24) -> List[ResolvedIncident]:
        """Get incidents from last N hours."""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=hours)

        return [i for i in self.incidents if i.resolved_at > cutoff]


class SimilarIncidentMatcher:
    """Helper for matching current incidents to historical ones."""
    
    @staticmethod
    def match_and_suggest_playbook(
        current_symptom: str,
        history: IncidentHistory,
        container: Optional[str] = None,
        service: Optional[str] = None,
    ) -> Optional[tuple[ResolvedIncident, float]]:
        """
        Find best matching incident and suggest its playbook.
        
        Returns:
            Tuple of (ResolvedIncident, confidence_score) or None
        """
        similar_incidents = history.find_similar(
            symptom=current_symptom,
            container=container,
            service=service,
            limit=1,
        )
        
        if not similar_incidents:
            return None
        
        best_match = similar_incidents[0]
        
        # Calculate confidence (simple heuristic)
        confidence = 0.8  # Base confidence for symptom match
        
        # Boost confidence if container/service matches
        if container and best_match.context.container == container:
            confidence += 0.1
        if service and best_match.context.service == service:
            confidence += 0.1
        
        confidence = min(confidence, 0.99)  # Cap at 0.99
        
        return (best_match, confidence)
