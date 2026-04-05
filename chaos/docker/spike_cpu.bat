@echo off
REM Spike CPU in demo-app container
echo [CHAOS] Spiking CPU on demo-app...
docker exec autoops-demo-demo-app-1 sh -c "dd if=/dev/zero of=/dev/null bs=1M &" 2>nul
echo [CHAOS] CPU stress running. Kill with: docker exec autoops-demo-demo-app-1 pkill dd
