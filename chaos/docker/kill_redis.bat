@echo off
REM Kill the Redis demo container
echo [CHAOS] Stopping demo-redis container...
docker stop autoops-demo-demo-redis-1 2>nul || docker stop demo-redis 2>nul
echo [CHAOS] demo-redis stopped.
