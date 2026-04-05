@echo off
REM Kill the MongoDB demo container — triggers incident detection
echo [CHAOS] Stopping mongodb-demo container...
docker stop autoops-demo-mongodb-demo-1 2>nul || docker stop mongodb-demo 2>nul
echo [CHAOS] mongodb-demo stopped. AutoOps AI should detect this within %POLLING_INTERVAL_SECONDS% seconds.
