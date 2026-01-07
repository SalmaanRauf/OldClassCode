"""
Thread-safe session management with proper locking and cleanup.
"""

import asyncio
import threading
import time
import uuid
from typing import Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import weakref

@dataclass
class SessionInfo:
    """Information about a session for cleanup purposes."""
    session_id: str
    created_at: datetime
    last_accessed: datetime
    context_ref: Any  # Weak reference to avoid circular references

class ThreadSafeSessionManager:
    """Thread-safe session manager with automatic cleanup."""
    
    def __init__(self, cleanup_interval: int = 300, max_idle_time: int = 3600):
        """
        Initialize session manager.
        
        Args:
            cleanup_interval: How often to run cleanup (seconds)
            max_idle_time: Maximum idle time before session cleanup (seconds)
        """
        self._lock = threading.RLock()
        self._sessions: Dict[str, Any] = {}
        self._session_info: Dict[str, SessionInfo] = {}
        self._cleanup_interval = cleanup_interval
        self._max_idle_time = max_idle_time
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
    
    def start_cleanup_task(self):
        """Start the background cleanup task."""
        if not self._running:
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    def stop_cleanup_task(self):
        """Stop the background cleanup task."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
    
    async def _cleanup_loop(self):
        """Background task to clean up old sessions."""
        while self._running:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_old_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in cleanup loop: {e}")
    
    async def _cleanup_old_sessions(self):
        """Clean up sessions that have been idle too long."""
        with self._lock:
            now = datetime.utcnow()
            to_remove = []
            
            for session_id, info in self._session_info.items():
                if (now - info.last_accessed).total_seconds() > self._max_idle_time:
                    to_remove.append(session_id)
            
            for session_id in to_remove:
                self._remove_session(session_id)
            
            if to_remove:
                print(f"Cleaned up {len(to_remove)} idle sessions")
    
    def _remove_session(self, session_id: str):
        """Remove a session and its info."""
        if session_id in self._sessions:
            del self._sessions[session_id]
        if session_id in self._session_info:
            del self._session_info[session_id]
    
    def get_or_create_session(self, session_id: Optional[str] = None, factory_func=None) -> tuple[str, Any]:
        """
        Get or create a session with proper locking.
        
        Args:
            session_id: Optional session ID. If None, generates a new one.
            factory_func: Function to create new session context.
            
        Returns:
            Tuple of (session_id, session_context)
        """
        with self._lock:
            # Generate session ID if not provided
            if not session_id:
                session_id = str(uuid.uuid4())
            
            # Check if session exists
            if session_id in self._sessions:
                # Update last accessed time
                if session_id in self._session_info:
                    self._session_info[session_id].last_accessed = datetime.utcnow()
                return session_id, self._sessions[session_id]
            
            # Create new session
            if factory_func:
                context = factory_func(session_id)
            else:
                context = {}
            
            self._sessions[session_id] = context
            self._session_info[session_id] = SessionInfo(
                session_id=session_id,
                created_at=datetime.utcnow(),
                last_accessed=datetime.utcnow(),
                context_ref=None
            )
            
            return session_id, context
    
    def remove_session(self, session_id: str):
        """Remove a specific session."""
        with self._lock:
            self._remove_session(session_id)
    
    def get_session_count(self) -> int:
        """Get the number of active sessions."""
        with self._lock:
            return len(self._sessions)
    
    def get_session_info(self) -> Dict[str, Dict[str, Any]]:
        """Get information about all sessions (for monitoring)."""
        with self._lock:
            return {
                session_id: {
                    "created_at": info.created_at.isoformat(),
                    "last_accessed": info.last_accessed.isoformat(),
                    "age_seconds": (datetime.utcnow() - info.created_at).total_seconds(),
                    "idle_seconds": (datetime.utcnow() - info.last_accessed).total_seconds()
                }
                for session_id, info in self._session_info.items()
            }

# Global session manager instance
session_manager = ThreadSafeSessionManager()

